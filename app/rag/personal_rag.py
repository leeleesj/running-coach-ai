"""
Personal RAG — 내 과거 운동 데이터 벡터 검색

역할:
  1. DB의 77개 운동 데이터를 텍스트화 → 임베딩 → ChromaDB 저장
  2. 오늘 운동과 유사한 과거 운동 Top 3 검색
  3. "3개월 전 대비 페이스 7초 향상, 심박 3bpm 안정" 비교 텍스트 생성
  4. local_llm.py 프롬프트에 주입할 RAG 컨텍스트 반환

임베딩 모델: paraphrase-multilingual-MiniLM-L12-v2
  - 한국어/다국어 지원, 117MB
  - Knowledge RAG와 동일 모델 사용 (벡터 공간 통일 필수)
  - 교체 실험은 한 사이클 완료 후 진행
"""

import sqlite3
from datetime import datetime
from pathlib import Path

import chromadb
from sentence_transformers import SentenceTransformer

# 설정
MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"
CHROMA_PATH = Path("data/chroma")
COLLECTION_NAME = "personal_runs"
DB_PATH = Path("data/running_coach.db")


def _get_zone_name(heartrate: float) -> str:
    """심박수 → 존 이름 (텍스트 표현에 사용)"""
    if heartrate <= 138:
        return "존1(매우가벼움)"
    elif heartrate <= 150:
        return "존2(유산소기반)"
    elif heartrate <= 162:
        return "존3(유산소파워)"
    elif heartrate <= 174:
        return "존4(무산소역치)"
    else:
        return "존5(최대강도)"


def _sec_to_pace_str(pace_sec: float) -> str:
    """초/km → '분:초' 문자열"""
    if not pace_sec:
        return "N/A"
    return f"{int(pace_sec // 60)}분{int(pace_sec % 60):02d}초"


def activity_to_text(activity: dict) -> str:
    """
    운동 데이터 → 임베딩용 자연어 텍스트
    존 이름을 포함해 의미론적 유사도 검색이 잘 되도록 구성
    """
    avg_hr = activity.get("avg_heartrate") or 0
    zone_name = _get_zone_name(avg_hr)
    pace_str = _sec_to_pace_str(activity.get("avg_pace_sec"))
    distance = round(activity.get("distance_km") or 0, 1)
    max_hr = activity.get("max_heartrate") or 0
    cadence = activity.get("avg_cadence") or "N/A"
    elevation = int(activity.get("elevation_gain") or 0)
    calories = int(activity.get("calories") or 0)

    return (
        f"거리 {distance}km {zone_name} 훈련, "
        f"평균 페이스 {pace_str}/km, "
        f"평균 심박 {avg_hr}bpm({zone_name}), "
        f"최고 심박 {max_hr}bpm, "
        f"케이던스 {cadence}spm, "
        f"고도 상승 {elevation}m, "
        f"칼로리 {calories}kcal"
    )


class PersonalRAG:
    """
    개인 운동 데이터 RAG 인터페이스

    사용 예시:
        rag = PersonalRAG()
        rag.build_index()                          # 최초 1회 또는 데이터 추가 시
        context = rag.get_rag_context(activity)    # local_llm.py에서 호출
    """

    def __init__(self):
        self._model = None   # 지연 로딩 (import 시 모델 다운로드 방지)
        self._collection = None

    @property
    def model(self) -> SentenceTransformer:
        """임베딩 모델 지연 로딩"""
        if self._model is None:
            print(f"임베딩 모델 로딩: {MODEL_NAME}")
            self._model = SentenceTransformer(MODEL_NAME)
        return self._model

    @property
    def collection(self):
        """ChromaDB 컬렉션 지연 로딩"""
        if self._collection is None:
            CHROMA_PATH.mkdir(parents=True, exist_ok=True)
            client = chromadb.PersistentClient(path=str(CHROMA_PATH))
            self._collection = client.get_or_create_collection(
                name=COLLECTION_NAME,
                metadata={"hnsw:space": "cosine"},  # 코사인 유사도 사용
            )
        return self._collection

    def upsert_activity(self, activity: dict) -> None:
        """
        운동 하나를 ChromaDB에 저장/업데이트
        새 운동 완료 시 Webhook 처리 흐름에서 호출
        """
        db_id = str(activity["id"])
        text = activity_to_text(activity)
        embedding = self.model.encode(text).tolist()

        self.collection.upsert(
            ids=[db_id],
            embeddings=[embedding],
            documents=[text],
            metadatas=[{
                "db_id": activity["id"],
                "date": activity.get("date", "")[:10],
                "distance_km": float(activity.get("distance_km") or 0),
                "avg_pace_sec": float(activity.get("avg_pace_sec") or 0),
                "avg_heartrate": float(activity.get("avg_heartrate") or 0),
                "max_heartrate": float(activity.get("max_heartrate") or 0),
                "elevation_gain": float(activity.get("elevation_gain") or 0),
                "avg_cadence": float(activity.get("avg_cadence") or 0),
                "calories": float(activity.get("calories") or 0),
            }],
        )

    def build_index(self) -> int:
        """
        DB의 모든 운동을 ChromaDB에 인덱싱
        최초 실행 또는 전체 재인덱싱 시 사용
        반환: 인덱싱된 운동 수
        """
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM activities WHERE type = 'Run' ORDER BY date"
        )
        rows = cursor.fetchall()
        conn.close()

        count = 0
        for row in rows:
            activity = dict(row)
            if not activity.get("avg_heartrate"):
                continue  # 심박 데이터 없는 운동 제외
            self.upsert_activity(activity)
            count += 1

        print(f"인덱싱 완료: {count}개 운동 → ChromaDB({COLLECTION_NAME})")
        return count

    def search_similar(
        self,
        activity: dict,
        n_results: int = 3,
        exclude_db_id: int = None,
    ) -> list[dict]:
        """
        오늘 운동과 유사한 과거 운동 Top N 검색
        exclude_db_id: 오늘 운동 자신 제외 (이미 인덱스에 있을 경우)

        반환: [{"metadata": {...}, "document": "...", "distance": 0.xx}, ...]
        """
        total = self.collection.count()
        if total == 0:
            return []

        text = activity_to_text(activity)
        embedding = self.model.encode(text).tolist()

        # 여유분 더 가져온 뒤 자신 제외 처리
        fetch_n = min(n_results + 5, total)
        results = self.collection.query(
            query_embeddings=[embedding],
            n_results=fetch_n,
            include=["metadatas", "documents", "distances"],
        )

        # 오늘 날짜 기준으로 과거 운동만 포함
        today_date = activity.get("date", "")[:10]

        items = []
        for meta, doc, dist in zip(
            results["metadatas"][0],
            results["documents"][0],
            results["distances"][0],
        ):
            # 자기 자신 제외
            if exclude_db_id and meta.get("db_id") == exclude_db_id:
                continue
            # 오늘 운동 제외 (같은 날짜 포함 → 자기 자신 or 같은 날 다른 운동)
            if today_date and meta.get("date", "") >= today_date:
                continue
            # exclude_db_id 없을 때도 오늘 날짜 운동은 위에서 이미 제외됨
            items.append({
                "metadata": meta,
                "document": doc,
                "distance": round(dist, 4),
            })
            if len(items) >= n_results:
                break

        return items

    def build_comparison_text(
        self,
        today: dict,
        similar: list[dict],
    ) -> str:
        """
        오늘 운동과 유사 과거 운동의 비교 텍스트 생성
        "3개월 전 유사 운동 대비 페이스 7초 향상, 심박 3bpm 안정" 형태
        """
        if not similar:
            return ""

        today_date = datetime.fromisoformat(today.get("date", "")[:10])
        today_pace = today.get("avg_pace_sec") or 0
        today_hr = today.get("avg_heartrate") or 0
        today_dist = today.get("distance_km") or 0

        lines = [
            "## 과거 유사 운동 데이터 (반드시 아래 수치를 summary 또는 heartrate_analysis에 인용할 것)",
            "※ 예시: \"1개월 전 유사 훈련(160bpm) 대비 오늘 심박이 4bpm 안정됐고, 페이스는 9초 저하됐습니다.\"",
            "※ progress 필드에도 동일 수치를 한 문장으로 요약하세요.",
        ]

        for i, item in enumerate(similar, 1):
            meta = item["metadata"]
            past_date_str = meta.get("date", "")
            past_pace = meta.get("avg_pace_sec") or 0
            past_hr = meta.get("avg_heartrate") or 0
            past_dist = meta.get("distance_km") or 0

            # 날짜 차이 계산
            try:
                past_date = datetime.fromisoformat(past_date_str)
                days_diff = (today_date - past_date).days
                if days_diff >= 30:
                    period = f"{days_diff // 30}개월 전"
                elif days_diff >= 7:
                    period = f"{days_diff // 7}주 전"
                else:
                    period = f"{days_diff}일 전"
            except Exception:
                period = "과거"

            # 지표 비교 (양수 = 오늘이 더 좋음)
            pace_diff = past_pace - today_pace   # 양수 = 오늘 더 빠름
            hr_diff = past_hr - today_hr          # 양수 = 오늘 심박 낮음(효율적)
            dist_diff = today_dist - past_dist    # 양수 = 오늘 더 많이 달림

            pace_str = (
                f"페이스 {abs(int(pace_diff))}초 {'향상' if pace_diff > 0 else '저하'}"
                if abs(pace_diff) >= 3 else "페이스 유사"
            )
            hr_str = (
                f"심박 {abs(int(hr_diff))}bpm {'안정' if hr_diff > 0 else '상승'}"
                if abs(hr_diff) >= 2 else "심박 유사"
            )
            dist_str = (
                f"거리 {abs(round(dist_diff, 1))}km {'증가' if dist_diff > 0 else '감소'}"
                if abs(dist_diff) >= 0.5 else "거리 유사"
            )

            lines.append(
                f"{i}. {period} ({past_date_str}) "
                f"거리 {past_dist:.1f}km 심박 {past_hr:.0f}bpm → "
                f"{pace_str}, {hr_str}, {dist_str}"
            )

        return "\n".join(lines)

    def get_comparison_data(
        self,
        activity: dict,
        exclude_db_id: int = None,
    ) -> list[dict]:
        """
        telegram 표시용 구조화된 비교 데이터 반환
        LLM 요약에 의존하지 않고 수치를 직접 표시하기 위해 사용
        반환: [{"period": "1개월 전", "date": "2026-02-28", "distance_km": ..., ...}, ...]
        """
        similar = self.search_similar(activity, n_results=3, exclude_db_id=exclude_db_id)
        if not similar:
            return []

        today_str = activity.get("date", "")[:10]
        today_date = datetime.fromisoformat(today_str) if today_str else None
        today_pace = activity.get("avg_pace_sec") or 0
        today_hr = activity.get("avg_heartrate") or 0
        today_dist = activity.get("distance_km") or 0

        result = []
        for item in similar:
            meta = item["metadata"]
            past_date_str = meta.get("date", "")
            past_pace = meta.get("avg_pace_sec") or 0
            past_hr = meta.get("avg_heartrate") or 0
            past_dist = meta.get("distance_km") or 0

            period = "과거"
            if today_date and past_date_str:
                try:
                    days_diff = (today_date - datetime.fromisoformat(past_date_str)).days
                    if days_diff >= 30:
                        period = f"{days_diff // 30}개월 전"
                    elif days_diff >= 7:
                        period = f"{days_diff // 7}주 전"
                    else:
                        period = f"{days_diff}일 전"
                except Exception:
                    pass

            result.append({
                "period": period,
                "date": past_date_str,
                "distance_km": round(past_dist, 1),
                "avg_heartrate": round(past_hr),
                "avg_pace_sec": past_pace,
                "pace_diff": past_pace - today_pace,   # 양수 = 오늘 더 빠름
                "hr_diff": past_hr - today_hr,          # 양수 = 오늘 심박 낮음(효율적)
                "dist_diff": today_dist - past_dist,    # 양수 = 오늘 더 많이 달림
            })

        return result

    def get_rag_context(
        self,
        activity: dict,
        exclude_db_id: int = None,
    ) -> str:
        """
        local_llm.py analyze_activity()에 주입할 RAG 컨텍스트 반환
        인덱스가 비어있거나 유사 운동이 없으면 빈 문자열 반환
        """
        if self.collection.count() == 0:
            return ""

        similar = self.search_similar(activity, n_results=3, exclude_db_id=exclude_db_id)
        if not similar:
            return ""

        return self.build_comparison_text(activity, similar)


# 싱글턴 인스턴스 (앱 전체에서 모델을 한 번만 로딩)
_rag_instance: PersonalRAG | None = None


def get_personal_rag() -> PersonalRAG:
    """PersonalRAG 싱글턴 반환"""
    global _rag_instance
    if _rag_instance is None:
        _rag_instance = PersonalRAG()
    return _rag_instance
