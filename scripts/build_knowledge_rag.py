"""
Knowledge RAG 인덱스 구축 스크립트
PMC XML API로 논문 텍스트 수집 → ChromaDB(running_knowledge) 저장

실행: uv run python scripts/build_knowledge_rag.py
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.rag.knowledge_rag import get_knowledge_rag, is_digital_pdf

# PMC 전문 무료 논문 (XML API로 자동 수집)
PMC_PAPERS = [
    {"pmc_id": "PMC10354346", "paper_id": "A-4", "topic": "심박존 HRV 처방",       "title": "Gronwald 2023 — HRV 기반 존 처방"},
    {"pmc_id": "PMC11377285", "paper_id": "B-1", "topic": "ITBS 치료",             "title": "Sanchez-Alvarado 2024 — ITBS 보존치료"},
    {"pmc_id": "PMC7740062",  "paper_id": "C-1", "topic": "슬개대퇴통증 PFPS",     "title": "Willy 2020 — PFPS 현대적 접근"},
    {"pmc_id": "PMC9441414",  "paper_id": "C-2", "topic": "케이던스 부상 예방",     "title": "Bramah 2022 — 케이던스 메타분석"},
    {"pmc_id": "PMC4763846",  "paper_id": "D-1", "topic": "발 외회전 무릎 하중",   "title": "Pappas 2016 — 발 외회전 무릎 하중"},
    {"pmc_id": "PMC10773390", "paper_id": "D-2", "topic": "보행 비대칭 부상 위험", "title": "Bertelsen 2024 — 보행 비대칭"},
    {"pmc_id": "PMC4555089",  "paper_id": "F-1", "topic": "러닝 이코노미 케이던스", "title": "Barnes 2015 — 러닝 이코노미"},
    {"pmc_id": "PMC10611166", "paper_id": "F-2", "topic": "젖산역치 심박 반응",     "title": "Festa 2023 — LT 심박 반응"},
]

# PDF 수동 다운로드 논문 (data/papers/ 에 있을 때만 인덱싱)
PDF_PAPERS = [
    {"filename": "A1_seiler_2010_intensity_distribution.pdf", "paper_id": "A-1", "topic": "훈련 강도 분배 80/20"},
    {"filename": "A2_munoz_2014_polarized_training.pdf",      "paper_id": "A-2", "topic": "폴라라이즈드 훈련"},
    {"filename": "A3_londeree_1990_hrmax_lt.pdf",             "paper_id": "A-3", "topic": "HRmax 젖산역치"},
    {"filename": "B2_louw_2012_itbs_review.pdf",              "paper_id": "B-2", "topic": "ITBS 역학"},
    {"filename": "E1_damsted_2020_acwr_injury.pdf",           "paper_id": "E-1", "topic": "훈련 부하 ACWR 부상"},
]

PAPERS_DIR = Path("data/papers")


def main():
    print("Knowledge RAG 인덱스 구축 시작\n")

    rag = get_knowledge_rag()
    existing = rag.collection.count()
    print(f"기존 인덱스: {existing}개 청크\n")

    total_chunks = 0

    # ── PMC XML API 자동 수집 ─────────────────────────────────────────
    print("=" * 55)
    print("PMC XML API 자동 수집")
    print("=" * 55)

    for paper in PMC_PAPERS:
        print(f"\n[{paper['paper_id']}] {paper['topic']}")
        print(f"  PMC: {paper['pmc_id']}")
        chunks = rag.add_paper_from_pmc(
            pmc_id=paper["pmc_id"],
            paper_id=paper["paper_id"],
            topic=paper["topic"],
            source_title=paper["title"],
        )
        total_chunks += chunks
        # NCBI API 부하 방지 (초당 3 요청 제한)
        if chunks > 0:
            time.sleep(1.0)

    # ── PDF 수동 다운로드 논문 ─────────────────────────────────────────
    print("\n" + "=" * 55)
    print("PDF 수동 다운로드 논문 확인")
    print("=" * 55)

    PAPERS_DIR.mkdir(parents=True, exist_ok=True)
    for paper in PDF_PAPERS:
        pdf_path = PAPERS_DIR / paper["filename"]
        print(f"\n[{paper['paper_id']}] {paper['topic']}")
        if not pdf_path.exists():
            print(f"  파일 없음 (ResearchGate 수동 다운로드 필요): {paper['filename']}")
            continue
        if not is_digital_pdf(pdf_path):
            print(f"  스캔 PDF — OCR 미구현, 건너뜀")
            continue
        chunks = rag.add_paper(
            pdf_path=pdf_path,
            paper_id=paper["paper_id"],
            topic=paper["topic"],
            source_title=paper["filename"],
        )
        total_chunks += chunks

    # ── 결과 요약 ─────────────────────────────────────────────────────
    print(f"\n{'=' * 55}")
    print(f"인덱싱 완료: 총 {total_chunks}개 청크 추가")
    print(f"전체 인덱스: {rag.collection.count()}개 청크")
    print("=" * 55)

    # ── 검색 품질 확인 ─────────────────────────────────────────────────
    if rag.collection.count() == 0:
        print("\n인덱스 비어있음 — 검색 품질 확인 건너뜀")
        return

    print("\n검색 품질 확인")
    print("=" * 55)

    test_queries = [
        ("zone 2 low intensity aerobic heart rate 80 percent",   "존2 유산소 훈련"),
        ("IT band syndrome iliotibial treatment hip abductor",   "ITBS 부상"),
        ("patellofemoral pain syndrome knee cadence load",       "PFPS 무릎 통증"),
        ("foot toe-out external rotation knee moment",          "발 외회전 비대칭"),
        ("acute chronic workload ratio injury risk running",     "훈련 부하 ACWR"),
        ("running economy cadence stride length oxygen cost",    "러닝 이코노미"),
        ("lactate threshold heart rate cardiac drift",           "젖산역치 심박"),
    ]

    for query, label in test_queries:
        results = rag.search(query, n_results=2)
        print(f"\n쿼리: {label}")
        if results:
            for r in results:
                meta = r["metadata"]
                print(f"  [{meta['paper_id']}] {meta['topic']} (유사도:{1-r['distance']:.3f})")
                print(f"  {r['document'][:120]}...")
        else:
            print("  결과 없음")


if __name__ == "__main__":
    main()
