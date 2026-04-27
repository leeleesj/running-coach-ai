"""
Knowledge RAG — 러닝 전문 지식 벡터 검색

역할:
  1. PMC XML API로 논문 텍스트 수집 → 청크 분할 → 임베딩 → ChromaDB 저장
  2. PDF가 있으면 PyMuPDF로 파싱 (병행 지원)
  3. 분석 시 관련 지식 검색 → 프롬프트 주입
  4. Personal RAG와 동일한 임베딩 모델 사용 (벡터 공간 통일)

텍스트 수집 전략:
  - PMC 논문: NCBI E-utilities XML API (무료, 프로그래밍 접근)
  - PDF 있으면: PyMuPDF 텍스트 추출 (병행)

청킹 전략:
  - 고정 크기: 512 문자 / 80 문자 overlap
"""

import re
import xml.etree.ElementTree as ET
from pathlib import Path

import chromadb
import httpx
from sentence_transformers import SentenceTransformer

# 설정 (Personal RAG와 동일한 모델 — 벡터 공간 통일)
MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"
CHROMA_PATH = Path("data/chroma")
COLLECTION_NAME = "running_knowledge"
PAPERS_DIR = Path("data/papers")

CHUNK_SIZE = 512
CHUNK_OVERLAP = 80

NCBI_EFETCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"


# ── PMC XML 파싱 ─────────────────────────────────────────────────────────────

def fetch_pmc_xml(pmc_id: str) -> str:
    """PMC XML API로 논문 전문 텍스트 추출"""
    pmc_num = pmc_id.replace("PMC", "")
    resp = httpx.get(
        NCBI_EFETCH,
        params={"db": "pmc", "id": f"PMC{pmc_num}", "rettype": "xml"},
        timeout=30.0,
    )
    resp.raise_for_status()
    return _parse_pmc_xml(resp.text)


def _parse_pmc_xml(xml_text: str) -> str:
    """PMC XML에서 본문 텍스트만 추출 (서지정보·참고문헌 제외)"""
    root = ET.fromstring(xml_text)

    # 네임스페이스 제거 헬퍼
    def strip_ns(tag: str) -> str:
        return tag.split("}")[-1] if "}" in tag else tag

    def extract_text(elem) -> str:
        texts = []
        if elem.text:
            texts.append(elem.text.strip())
        for child in elem:
            tag = strip_ns(child.tag)
            # 참고문헌·저자정보·표 제목 등 제외
            if tag in ("ref-list", "contrib-group", "author-notes",
                       "pub-date", "history", "permissions"):
                continue
            texts.append(extract_text(child))
            if child.tail:
                texts.append(child.tail.strip())
        return " ".join(t for t in texts if t)

    # body만 추출 (abstract + body)
    sections = []
    for elem in root.iter():
        tag = strip_ns(elem.tag)
        if tag in ("abstract", "body"):
            sections.append(extract_text(elem))

    return clean_text("\n\n".join(sections))


def clean_text(text: str) -> str:
    """텍스트 정제"""
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r" {2,}", " ", text)
    text = re.sub(r"^\d+\s*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"-\n([a-z])", r"\1", text)
    return text.strip()


def extract_text_from_pdf(path: Path) -> str:
    """PDF에서 텍스트 추출 (PyMuPDF)"""
    try:
        import fitz
        doc = fitz.open(str(path))
        pages = [page.get_text() for page in doc if page.get_text().strip()]
        doc.close()
        return clean_text("\n\n".join(pages))
    except Exception as e:
        print(f"  PDF 파싱 실패: {e}")
        return ""


def is_digital_pdf(path: Path) -> bool:
    """디지털 PDF 여부 확인 (텍스트 레이어 있으면 True)"""
    try:
        import fitz
        doc = fitz.open(str(path))
        text = doc[0].get_text() if len(doc) > 0 else ""
        doc.close()
        return len(text.strip()) >= 50
    except Exception:
        return False


# ── 청킹 ────────────────────────────────────────────────────────────────────

def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """
    고정 크기 청킹 (문장 경계 존중)
    chunk_size: 청크당 최대 문자 수
    overlap: 이전 청크와 겹치는 문자 수
    """
    # 문장 단위로 분리
    sentences = re.split(r"(?<=[.!?])\s+", text)

    chunks = []
    current = ""
    overlap_buffer = ""

    for sentence in sentences:
        # 청크 크기 초과 시 저장 후 새 청크 시작
        if len(current) + len(sentence) > chunk_size and current:
            chunks.append(current.strip())
            # overlap: 마지막 N 문자 가져오기
            overlap_buffer = current[-overlap:] if len(current) > overlap else current
            current = overlap_buffer + " " + sentence
        else:
            current += (" " if current else "") + sentence

    if current.strip():
        chunks.append(current.strip())

    # 너무 짧은 청크 제거 (50자 미만)
    return [c for c in chunks if len(c) >= 50]


# ── Knowledge RAG 클래스 ─────────────────────────────────────────────────────

class KnowledgeRAG:
    """
    러닝 전문 지식 RAG 인터페이스

    사용 예시:
        rag = KnowledgeRAG()
        rag.add_paper("data/papers/B1_itbs.pdf", paper_id="B-1", topic="ITBS 치료")
        context = rag.get_knowledge_context("IT밴드 증후군 치료 방법")
    """

    def __init__(self):
        self._model = None
        self._collection = None

    @property
    def model(self) -> SentenceTransformer:
        if self._model is None:
            print(f"임베딩 모델 로딩: {MODEL_NAME}")
            self._model = SentenceTransformer(MODEL_NAME)
        return self._model

    @property
    def collection(self):
        if self._collection is None:
            CHROMA_PATH.mkdir(parents=True, exist_ok=True)
            client = chromadb.PersistentClient(path=str(CHROMA_PATH))
            self._collection = client.get_or_create_collection(
                name=COLLECTION_NAME,
                metadata={"hnsw:space": "cosine"},
            )
        return self._collection

    def add_paper_from_pmc(
        self,
        pmc_id: str,
        paper_id: str,
        topic: str,
        source_title: str = "",
    ) -> int:
        """
        PMC XML API로 논문 텍스트 수집 → 청킹 → ChromaDB에 저장
        반환: 저장된 청크 수
        """
        # 첫 번째 청크가 이미 존재하면 스킵 (이미 인덱싱됨)
        existing = self.collection.get(ids=[f"{paper_id}_chunk_000"])
        if existing["ids"]:
            print(f"  이미 인덱싱됨: {paper_id}")
            return 0

        print(f"  PMC XML 수집 중: {pmc_id}")
        try:
            text = fetch_pmc_xml(pmc_id)
        except Exception as e:
            print(f"  PMC XML 수집 실패: {e}")
            return 0

        if not text:
            print(f"  텍스트 없음: {pmc_id}")
            return 0

        print(f"  텍스트 추출: {len(text)}자")

        chunks = chunk_text(text)
        print(f"  청킹 완료: {len(chunks)}개 청크")

        saved = 0
        for i, chunk in enumerate(chunks):
            chunk_id = f"{paper_id}_chunk_{i:03d}"

            existing = self.collection.get(ids=[chunk_id])
            if existing["ids"]:
                continue

            embedding = self.model.encode(chunk).tolist()
            self.collection.upsert(
                ids=[chunk_id],
                embeddings=[embedding],
                documents=[chunk],
                metadatas=[{
                    "paper_id": paper_id,
                    "topic": topic,
                    "source_title": source_title or pmc_id,
                    "chunk_index": i,
                    "total_chunks": len(chunks),
                }],
            )
            saved += 1

        print(f"  저장 완료: {saved}개 청크 → ChromaDB({COLLECTION_NAME})")
        return saved

    def add_paper(
        self,
        pdf_path: Path,
        paper_id: str,
        topic: str,
        source_title: str = "",
    ) -> int:
        """
        PDF 한 편을 파싱 → 청킹 → ChromaDB에 저장 (수동 다운로드 논문용)
        반환: 저장된 청크 수
        """
        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            print(f"  파일 없음: {pdf_path}")
            return 0

        # PDF 판별
        if not is_digital_pdf(pdf_path):
            print(f"  스캔 PDF (OCR 미구현): {pdf_path.name}")
            return 0

        # 텍스트 추출 및 정제
        raw_text = extract_text_from_pdf(pdf_path)
        text = clean_text(raw_text)
        print(f"  텍스트 추출: {len(text)}자")

        # 청킹
        chunks = chunk_text(text)
        print(f"  청킹 완료: {len(chunks)}개 청크")

        # 임베딩 및 저장
        saved = 0
        for i, chunk in enumerate(chunks):
            chunk_id = f"{paper_id}_chunk_{i:03d}"

            existing = self.collection.get(ids=[chunk_id])
            if existing["ids"]:
                continue

            embedding = self.model.encode(chunk).tolist()
            self.collection.upsert(
                ids=[chunk_id],
                embeddings=[embedding],
                documents=[chunk],
                metadatas=[{
                    "paper_id": paper_id,
                    "topic": topic,
                    "source_title": source_title,
                    "chunk_index": i,
                    "total_chunks": len(chunks),
                }],
            )
            saved += 1

        print(f"  저장 완료: {saved}개 청크 → ChromaDB({COLLECTION_NAME})")
        return saved

    def search(
        self,
        query: str,
        n_results: int = 3,
        topic_filter: str = None,
    ) -> list[dict]:
        """
        쿼리로 관련 지식 청크 검색
        topic_filter: 특정 주제만 검색 (예: "ITBS")
        반환: [{"document": "...", "metadata": {...}, "distance": 0.xx}, ...]
        """
        if self.collection.count() == 0:
            return []

        embedding = self.model.encode(query).tolist()

        where = {"topic": {"$eq": topic_filter}} if topic_filter else None

        results = self.collection.query(
            query_embeddings=[embedding],
            n_results=min(n_results, self.collection.count()),
            include=["documents", "metadatas", "distances"],
            where=where,
        )

        return [
            {
                "document": doc,
                "metadata": meta,
                "distance": round(dist, 4),
            }
            for doc, meta, dist in zip(
                results["documents"][0],
                results["metadatas"][0],
                results["distances"][0],
            )
        ]

    def get_knowledge_context(
        self,
        activity: dict,
        avg_heartrate: float = None,
        injury_keywords: list[str] = None,
    ) -> str:
        """
        운동 데이터 기반으로 관련 지식 검색 → 프롬프트 주입용 텍스트 반환

        검색 쿼리 자동 구성:
          - 심박존 관련 쿼리
          - 부상 관련 쿼리 (injury_keywords 있을 때)
        """
        if self.collection.count() == 0:
            return ""

        hr = avg_heartrate or activity.get("avg_heartrate", 0)
        queries = []

        # 심박존 기반 쿼리
        if hr <= 150:
            queries.append("zone 2 low intensity aerobic training heart rate")
        elif hr <= 162:
            queries.append("zone 3 aerobic power tempo running heart rate lactate")
        elif hr <= 174:
            queries.append("zone 4 lactate threshold anaerobic running intensity")
        else:
            queries.append("zone 5 maximal intensity interval running VO2max")

        # 부상 관련 쿼리
        if injury_keywords:
            queries.extend(injury_keywords)

        # 각 쿼리로 검색 후 합치기 (중복 제거)
        seen_ids = set()
        all_results = []
        for query in queries:
            results = self.search(query, n_results=2)
            for r in results:
                chunk_id = f"{r['metadata']['paper_id']}_{r['metadata']['chunk_index']}"
                if chunk_id not in seen_ids and r["distance"] < 0.5:
                    seen_ids.add(chunk_id)
                    all_results.append(r)

        if not all_results:
            return ""

        # 프롬프트 텍스트 구성
        lines = [
            "## 관련 연구 근거 (아래 내용을 코칭 분석에 참고하되, 자연스럽게 녹여서 사용하세요)",
        ]
        for r in all_results[:3]:  # 최대 3개
            meta = r["metadata"]
            lines.append(
                f"[{meta['topic']}] {r['document'][:300]}..."
                if len(r["document"]) > 300
                else f"[{meta['topic']}] {r['document']}"
            )

        return "\n".join(lines)


# 싱글턴
_knowledge_rag_instance: KnowledgeRAG | None = None


def get_knowledge_rag() -> KnowledgeRAG:
    global _knowledge_rag_instance
    if _knowledge_rag_instance is None:
        _knowledge_rag_instance = KnowledgeRAG()
    return _knowledge_rag_instance
