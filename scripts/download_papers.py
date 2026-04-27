"""
PubMed Central(PMC) 논문 PDF 자동 다운로드 스크립트

PMC 전문 무료 논문 9편을 data/papers/ 에 저장
ResearchGate 수동 다운로드 필요 논문 4편은 안내만 출력

실행: uv run python scripts/download_papers.py
"""

import asyncio
import httpx
from pathlib import Path

PAPERS_DIR = Path("data/papers")

# PMC 전문 무료 논문 (자동 다운로드)
PMC_PAPERS = [
    {
        "id": "A-4",
        "title": "HRV 기반 존 처방 체계적 리뷰 (Gronwald 2023)",
        "pmc": "PMC10354346",
        "pmid": "37462761",
        "filename": "A4_gronwald_2023_hrv_zones.pdf",
    },
    {
        "id": "B-1",
        "title": "ITBS 보존치료 효과 (Sanchez-Alvarado 2024)",
        "pmc": "PMC11377285",
        "pmid": "39247485",
        "filename": "B1_sanchez_2024_itbs_treatment.pdf",
    },
    {
        "id": "C-1",
        "title": "PFPS 러너 현대적 접근 (Willy 2020)",
        "pmc": "PMC7740062",
        "pmid": "33196837",
        "filename": "C1_willy_2020_pfps_runners.pdf",
    },
    {
        "id": "C-2",
        "title": "케이던스 변화 → 부상·성능 메타분석 (Bramah 2022)",
        "pmc": "PMC9441414",
        "pmid": "36057913",
        "filename": "C2_bramah_2022_cadence_injury.pdf",
    },
    {
        "id": "D-1",
        "title": "발 외회전 → 무릎 하중 (Pappas 2016)",
        "pmc": "PMC4763846",
        "pmid": "26957926",
        "filename": "D1_pappas_2016_foot_rotation_knee.pdf",
    },
    {
        "id": "D-2",
        "title": "보행 비대칭 → 부상 위험 (Bertelsen 2024)",
        "pmc": "PMC10773390",
        "pmid": "38196940",
        "filename": "D2_bertelsen_2024_gait_asymmetry.pdf",
    },
    {
        "id": "F-1",
        "title": "러닝 이코노미 종합 리뷰 (Barnes 2015)",
        "pmc": "PMC4555089",
        "pmid": "27747844",
        "filename": "F1_barnes_2015_running_economy.pdf",
    },
    {
        "id": "F-2",
        "title": "LT별 심박 개인 반응 (Festa 2023)",
        "pmc": "PMC10611166",
        "pmid": None,
        "filename": "F2_festa_2023_lt_heartrate.pdf",
    },
]

# ResearchGate 수동 다운로드 필요 논문
MANUAL_PAPERS = [
    {
        "id": "A-1",
        "title": "Seiler — 훈련 강도 분배 원칙 (2010)",
        "pmid": "20861519",
        "researchgate": "https://www.researchgate.net/publication/45393888",
    },
    {
        "id": "A-2",
        "title": "폴라라이즈드 vs 역치간 훈련 (Muñoz 2014)",
        "pmid": "23752040",
        "researchgate": "https://www.researchgate.net/publication/249318497",
    },
    {
        "id": "A-3",
        "title": "HRmax%-젖산역치 관계 (Londeree 1990)",
        "pmid": "2373580",
        "researchgate": "검색 필요: 'Londeree 1990 percentages maximal heart rate'",
    },
    {
        "id": "B-2",
        "title": "ITBS 체계적 리뷰 (Louw 2012)",
        "pmid": "22994651",
        "researchgate": "https://www.researchgate.net/publication/231989637",
    },
]


async def download_pmc_pdf(paper: dict, client: httpx.AsyncClient) -> bool:
    """PMC에서 PDF 다운로드"""
    filename = PAPERS_DIR / paper["filename"]

    if filename.exists():
        print(f"  [{paper['id']}] 이미 존재, 스킵: {paper['filename']}")
        return True

    # PMC PDF URL 패턴
    pmc_id = paper["pmc"].replace("PMC", "")
    url = f"https://pmc.ncbi.nlm.nih.gov/articles/PMC{pmc_id}/pdf/"

    try:
        print(f"  [{paper['id']}] 다운로드 중: {paper['title'][:50]}")
        response = await client.get(url, follow_redirects=True, timeout=30.0)

        if response.status_code == 200 and b"%PDF" in response.content[:10]:
            filename.write_bytes(response.content)
            size_kb = len(response.content) // 1024
            print(f"  [{paper['id']}] 완료 ({size_kb}KB): {paper['filename']}")
            return True
        else:
            # PDF 직접 링크가 다를 수 있음 — article 페이지에서 링크 파싱 시도
            article_url = f"https://pmc.ncbi.nlm.nih.gov/articles/PMC{pmc_id}/"
            resp2 = await client.get(article_url, timeout=30.0)
            if resp2.status_code == 200:
                # PDF 링크 추출
                import re
                pdf_links = re.findall(
                    rf'/articles/PMC{pmc_id}/pdf/[^"\']+\.pdf', resp2.text
                )
                if pdf_links:
                    pdf_url = "https://pmc.ncbi.nlm.nih.gov" + pdf_links[0]
                    resp3 = await client.get(pdf_url, timeout=30.0)
                    if resp3.status_code == 200 and b"%PDF" in resp3.content[:10]:
                        filename.write_bytes(resp3.content)
                        size_kb = len(resp3.content) // 1024
                        print(f"  [{paper['id']}] 완료 ({size_kb}KB): {paper['filename']}")
                        return True

            print(f"  [{paper['id']}] 실패 (status={response.status_code}): {paper['title'][:40]}")
            return False

    except Exception as e:
        print(f"  [{paper['id']}] 에러: {e}")
        return False


async def main():
    PAPERS_DIR.mkdir(parents=True, exist_ok=True)
    print(f"저장 경로: {PAPERS_DIR.absolute()}\n")

    print("=" * 60)
    print("PMC 전문 무료 논문 자동 다운로드")
    print("=" * 60)

    success = 0
    fail = 0
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }

    async with httpx.AsyncClient(headers=headers) as client:
        for paper in PMC_PAPERS:
            ok = await download_pmc_pdf(paper, client)
            if ok:
                success += 1
            else:
                fail += 1
            await asyncio.sleep(1.5)  # PMC 서버 부하 방지

    print(f"\n자동 다운로드 결과: 성공 {success}편 / 실패 {fail}편")

    print("\n" + "=" * 60)
    print("수동 다운로드 필요 논문 (ResearchGate)")
    print("=" * 60)
    for p in MANUAL_PAPERS:
        print(f"\n[{p['id']}] {p['title']}")
        print(f"  PMID: {p['pmid']}")
        print(f"  URL: {p['researchgate']}")
        fname = f"{p['id'].lower().replace('-', '')}_{p['pmid']}.pdf"
        print(f"  저장 위치: data/papers/{fname}")

    # 다운로드된 파일 목록
    pdfs = list(PAPERS_DIR.glob("*.pdf"))
    print(f"\n현재 data/papers/ 에 PDF {len(pdfs)}편 있음:")
    for pdf in sorted(pdfs):
        size_kb = pdf.stat().st_size // 1024
        print(f"  {pdf.name} ({size_kb}KB)")


if __name__ == "__main__":
    asyncio.run(main())
