"""
평가 파이프라인 실행 스크립트
Qwen 분석 → Claude/Qwen LLM-as-Judge 채점 → 결과 저장 및 비교

실행 예시:
  # Claude judge로 평가 (Qwen 분석 포함)
  uv run python -m evaluation.run_evaluation --judge claude

  # Qwen judge로 평가 (기존 Qwen 출력 재사용)
  uv run python -m evaluation.run_evaluation --judge qwen --skip-qwen

  # 빠른 단일 채점 (3회 평균 대신 1회)
  uv run python -m evaluation.run_evaluation --judge claude --repeat 1

  # 두 judge 결과 비교 출력
  uv run python -m evaluation.run_evaluation --compare
"""

import asyncio
import json
import re
import sys
import argparse
from datetime import datetime
from pathlib import Path

import httpx
from dotenv import load_dotenv
import os

load_dotenv()

CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY")
OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_MODEL = "qwen2.5:14b"

TEST_CASES_PATH = Path("evaluation/test_cases.json")
RESULTS_DIR = Path("evaluation/results")


# ── Qwen 분석 ──────────────────────────────────────────────────────────────

def build_qwen_prompt(activity: dict) -> str:
    """평가용 Qwen 프롬프트 (local_llm.py와 동일한 구조)"""
    splits = activity.get("splits", [])
    splits_text = ""
    for s in splits:
        hr = s.get("heartrate", 0)
        pace_sec = s.get("pace_sec", 0)
        if hr and pace_sec:
            mins, secs = int(pace_sec // 60), int(pace_sec % 60)
            splits_text += f"  {s['km']}km: 페이스 {mins}:{secs:02d} /km, 심박 {hr}bpm\n"

    def get_zone(hr):
        if hr <= 138: return "존1 (매우 가벼움)"
        elif hr <= 150: return "존2 (유산소 기반)"
        elif hr <= 162: return "존3 (유산소 파워)"
        elif hr <= 174: return "존4 (무산소 역치)"
        else: return "존5 (최대 강도)"

    avg_hr = activity.get("avg_heartrate", 0)
    max_hr = activity.get("max_heartrate", 0)
    pace_sec = activity.get("avg_pace_sec", 0)
    pace_str = f"{int(pace_sec//60)}:{int(pace_sec%60):02d} /km" if pace_sec else "N/A"

    return f"""당신은 전문 러닝 코치입니다. 다음 운동 데이터를 분석해주세요.

## 내 개인 심박존 (애플워치 기준, 반드시 준수)
존1 (매우 가벼움):  138bpm 이하         → 페이스 10:00/km 이상
존2 (유산소 기반):  139~150bpm          → 페이스 약 8:30~9:30/km
존3 (유산소 파워):  151~162bpm          → 페이스 약 7:00~8:00/km
존4 (무산소 역치):  163~174bpm          → 페이스 약 5:30~6:30/km
존5 (최대 강도):    175bpm 이상          → 페이스 5:30/km 미만

⚠️ 중요: 존2 훈련 목표 심박은 반드시 139~150bpm 범위여야 함

## 오늘 운동 존 분석
평균 심박 {avg_hr}bpm → {get_zone(avg_hr)}
최고 심박 {max_hr}bpm → {get_zone(max_hr)}

## 러닝 용어 (반드시 아래 용어만 사용)
- 존2 조깅, 템포런, 인터벌, LSD, 회복 조깅, 휴식

## 오늘 운동 데이터
- 날짜: {activity.get('date', '')[:10]}
- 거리: {activity.get('distance_km', 0)}km
- 평균 페이스: {pace_str}
- 평균 심박수: {avg_hr}bpm
- 최고 심박수: {max_hr}bpm
- 케이던스: {activity.get('avg_cadence', 'N/A')}spm
- 칼로리: {activity.get('calories', 0)}kcal
- 고도 상승: {activity.get('elevation_gain', 0)}m

## km별 구간 데이터
{splits_text.rstrip() or "구간 데이터 없음"}

## 목표
- 하프마라톤 + 10km 대회에서 PB 갱신
- 심박수 안정화 (존2 훈련 비율 높이기)

## 응답 형식
반드시 아래 JSON으로만 응답하세요:

{{
  "summary": "오늘 운동 총평 (2~3문장, 존 정보 포함)",
  "heartrate_analysis": "심박수 존 분석 (개인 존 기준으로 정확하게, 2~3문장)",
  "pace_analysis": "구간별 페이스 패턴 분석 (2~3문장)",
  "tomorrow": {{
    "type": "훈련 종류 (휴식/존2 조깅/템포런/인터벌/LSD 중 하나)",
    "distance": "거리 (예: 5km)",
    "pace": "목표 페이스",
    "heartrate": "목표 심박수 (개인 존 범위 내로)"
  }},
  "marathon_status": "하프마라톤/10km PB 준비 현황 한 줄 요약"
}}"""


async def call_qwen(prompt: str) -> str:
    async with httpx.AsyncClient(timeout=120.0) as client:
        r = await client.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False,
                  "options": {"num_predict": 800, "temperature": 0.7}},
        )
    if r.status_code != 200:
        raise RuntimeError(f"Ollama 에러: {r.status_code}")
    return r.json().get("response", "")


# ── Judge ───────────────────────────────────────────────────────────────────

def build_judge_prompt(activity_text: str, llm_output: str) -> str:
    from evaluation.rubric import build_judge_prompt as _build
    return _build(activity_text, llm_output)


def parse_json_response(text: str) -> dict | None:
    try:
        text = re.sub(r"```json\s*", "", text)
        text = re.sub(r"```\s*", "", text)
        return json.loads(text.strip())
    except Exception:
        return None


async def call_claude_judge(prompt: str) -> dict | None:
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": CLAUDE_API_KEY, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": "claude-haiku-4-5-20251001", "max_tokens": 1024,
                  "messages": [{"role": "user", "content": prompt}]},
        )
    if r.status_code != 200:
        err = r.json().get("error", {}).get("message", "")
        print(f"  Claude 에러: {err[:80]}")
        return None
    return parse_json_response(r.json()["content"][0]["text"])


async def call_qwen_judge(prompt: str) -> dict | None:
    async with httpx.AsyncClient(timeout=120.0) as client:
        r = await client.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False,
                  "options": {"num_predict": 500, "temperature": 0.3}},
        )
    if r.status_code != 200:
        return None
    return parse_json_response(r.json().get("response", ""))


async def run_judge(activity_text: str, llm_output: str, judge: str, repeat: int) -> dict | None:
    """judge로 repeat회 채점 후 평균 반환"""
    prompt = build_judge_prompt(activity_text, llm_output)
    judge_fn = call_claude_judge if judge == "claude" else call_qwen_judge
    results = []

    for i in range(repeat):
        print(f"    {judge} 채점 {i+1}/{repeat}...")
        r = await judge_fn(prompt)
        if r:
            results.append(r)
        await asyncio.sleep(0.3)

    if not results:
        return None

    criteria = ["accuracy", "specificity", "personalization", "practicality", "korean_quality"]
    avg = {}
    for c in criteria:
        scores = [r[c]["score"] for r in results if c in r]
        reasons = [r[c]["reason"] for r in results if c in r]
        if scores:
            avg[c] = {"score": round(sum(scores) / len(scores), 2), "reason": reasons[0]}
    avg["total"] = round(sum(v["score"] for v in avg.values()), 2)
    return avg


def parse_qwen_output(text: str) -> str:
    """Qwen JSON 출력 → 읽기 좋은 텍스트"""
    try:
        data = parse_json_response(text)
        if not data:
            return text
        lines = []
        if data.get("summary"):
            lines.append(f"[총평] {data['summary']}")
        if data.get("heartrate_analysis"):
            lines.append(f"[심박] {data['heartrate_analysis']}")
        if data.get("tomorrow"):
            t = data["tomorrow"]
            lines.append(f"[내일] {t.get('type','')} {t.get('distance','')} "
                         f"페이스:{t.get('pace','')} 심박:{t.get('heartrate','')}")
        return "\n".join(lines) if lines else text
    except Exception:
        return text


# ── 비교 출력 ───────────────────────────────────────────────────────────────

def print_comparison(test_cases: list):
    """Claude judge vs Qwen judge 비교표 출력"""
    criteria = ["accuracy", "specificity", "personalization", "practicality", "korean_quality"]
    criteria_kr = ["정확성", "구체성", "개인화", "실용성", "한국어"]

    c_done = [tc for tc in test_cases if tc.get("final_scores_claude")]
    q_done = [tc for tc in test_cases if tc.get("final_scores_qwen")]

    if not c_done and not q_done:
        print("완료된 채점 없음")
        return

    print("\n" + "=" * 68)
    print("  베이스라인 평가 결과 비교 (Qwen2.5:14b 출력)")
    print(f"  {'항목':10s}  {'Claude Judge':>14s}  {'Qwen Judge':>12s}  {'차이':>8s}")
    print("=" * 68)

    for crit, crit_kr in zip(criteria, criteria_kr):
        c_scores = [tc["final_scores_claude"][crit]["score"] for tc in c_done if crit in tc.get("final_scores_claude", {})]
        q_scores = [tc["final_scores_qwen"][crit]["score"] for tc in q_done if crit in tc.get("final_scores_qwen", {})]
        c_avg = round(sum(c_scores) / len(c_scores), 2) if c_scores else 0
        q_avg = round(sum(q_scores) / len(q_scores), 2) if q_scores else 0
        diff = round(q_avg - c_avg, 2)
        diff_str = f"+{diff}" if diff > 0 else str(diff)
        flag = " ← Qwen 과대평가" if diff >= 0.5 else (" ← Qwen 과소평가" if diff <= -0.5 else "")
        print(f"  {crit_kr:10s}  {c_avg:>6.2f}/5.00    {q_avg:>5.2f}/5.00  {diff_str:>6s}{flag}")

    c_totals = [tc["final_scores_claude"]["total"] for tc in c_done]
    q_totals = [tc["final_scores_qwen"]["total"] for tc in q_done]
    c_total_avg = round(sum(c_totals) / len(c_totals), 2) if c_totals else 0
    q_total_avg = round(sum(q_totals) / len(q_totals), 2) if q_totals else 0
    diff_total = round(q_total_avg - c_total_avg, 2)
    diff_str = f"+{diff_total}" if diff_total > 0 else str(diff_total)

    print("-" * 68)
    print(f"  {'총점':10s}  {c_total_avg:>6.2f}/25.0   {q_total_avg:>5.2f}/25.0  {diff_str:>6s}")
    print(f"  {'케이스수':10s}  {len(c_done):>14d}  {len(q_done):>12d}")
    print("=" * 68)

    # 존별 정확성 비교
    print("\n존별 정확성 비교:")
    from collections import defaultdict
    c_zone = defaultdict(list)
    q_zone = defaultdict(list)
    for tc in c_done:
        zone = tc.get("expected_zone", "?")
        c_zone[zone].append(tc["final_scores_claude"]["accuracy"]["score"])
    for tc in q_done:
        zone = tc.get("expected_zone", "?")
        q_zone[zone].append(tc["final_scores_qwen"]["accuracy"]["score"])

    all_zones = sorted(set(list(c_zone.keys()) + list(q_zone.keys())))
    print(f"  {'존':10s}  {'Claude':>8s}  {'Qwen':>8s}  {'차이':>6s}")
    for zone in all_zones:
        c_avg = round(sum(c_zone[zone]) / len(c_zone[zone]), 2) if c_zone[zone] else 0
        q_avg = round(sum(q_zone[zone]) / len(q_zone[zone]), 2) if q_zone[zone] else 0
        diff = round(q_avg - c_avg, 2)
        diff_str = f"+{diff}" if diff > 0 else str(diff)
        print(f"  {zone:10s}  {c_avg:>6.2f}/5    {q_avg:>5.2f}/5  {diff_str:>6s}")

    # 자기평가 편향 분석
    print("\n분석:")
    if q_total_avg > c_total_avg + 1.0:
        print("  ⚠️  Qwen이 자기 출력을 Claude보다 크게 높게 평가")
        print("     → Self-enhancement bias 확인됨")
        print("     → 신뢰도 높은 점수는 Claude Judge 기준")
    elif abs(q_total_avg - c_total_avg) < 0.5:
        print("  ✅ 두 Judge 점수 차이 작음 → Qwen self-judge도 어느정도 신뢰 가능")
    else:
        print(f"  📊 Qwen Judge가 Claude보다 {diff_str}점 {'높음' if diff_total > 0 else '낮음'}")


# ── 메인 ────────────────────────────────────────────────────────────────────

async def main(judge: str, skip_qwen: bool, repeat: int, compare_only: bool):
    if not TEST_CASES_PATH.exists():
        print("test_cases.json 없음. 먼저 build_test_cases.py 실행하세요.")
        sys.exit(1)

    test_cases = json.loads(TEST_CASES_PATH.read_text())

    if compare_only:
        print_comparison(test_cases)
        return

    total = len(test_cases)
    score_key = f"final_scores_{judge}"

    for i, tc in enumerate(test_cases):
        print(f"\n[{i+1}/{total}] {tc['id']} | {tc['scenario']:15s} | "
              f"심박:{tc['activity']['avg_heartrate']:5.1f}bpm | 정답존:{tc['expected_zone']}")

        # Step 1: Qwen 분석
        if not skip_qwen and not tc.get("qwen_output"):
            print("  Qwen 분석 중...")
            try:
                tc["qwen_output"] = await call_qwen(build_qwen_prompt(tc["activity"]))
                print(f"  완료 ({len(tc['qwen_output'])}자)")
            except Exception as e:
                print(f"  Qwen 실패: {e}")
                continue
        elif not tc.get("qwen_output"):
            print("  qwen_output 없음, 건너뜀")
            continue
        else:
            print("  Qwen 출력 재사용")

        # Step 2: Judge 채점
        if tc.get(score_key):
            print(f"  [{judge}] 채점 이미 완료, 건너뜀")
            continue

        qwen_text = parse_qwen_output(tc["qwen_output"])
        scores = await run_judge(tc["activity_text"], qwen_text, judge=judge, repeat=repeat)
        if scores:
            tc[score_key] = scores
            print(f"  [{judge}] 총점 {scores['total']}/25 | 정확성 {scores['accuracy']['score']}/5")
        else:
            print(f"  [{judge}] 채점 실패")

        # 케이스마다 즉시 저장
        TEST_CASES_PATH.write_text(json.dumps(test_cases, ensure_ascii=False, indent=2))

    # 최종 결과 저장
    RESULTS_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = RESULTS_DIR / f"baseline_{judge}_{ts}.json"
    out.write_text(json.dumps(test_cases, ensure_ascii=False, indent=2))
    print(f"\n결과 저장: {out}")

    # 두 judge 모두 완료됐으면 비교 출력
    c_done = sum(1 for tc in test_cases if tc.get("final_scores_claude"))
    q_done = sum(1 for tc in test_cases if tc.get("final_scores_qwen"))
    if c_done > 0 and q_done > 0:
        print_comparison(test_cases)
    else:
        judge_label = "Claude" if judge == "claude" else "Qwen"
        print(f"\n{judge_label} Judge 완료 ({c_done if judge=='claude' else q_done}/{total})")
        other = "qwen" if judge == "claude" else "claude"
        print(f"비교 보려면: uv run python -m evaluation.run_evaluation --judge {other} --skip-qwen --repeat {repeat}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--judge", default="claude", choices=["claude", "qwen"])
    parser.add_argument("--skip-qwen", action="store_true")
    parser.add_argument("--repeat", type=int, default=3, help="judge 반복 횟수 (기본 3)")
    parser.add_argument("--compare", action="store_true", help="저장된 결과 비교만 출력")
    args = parser.parse_args()

    if args.judge == "qwen" and not args.skip_qwen:
        print("⚠️  Qwen self-judge: 자기 출력 평가 편향 있음. 학습 목적으로만 사용.\n")

    asyncio.run(main(
        judge=args.judge,
        skip_qwen=args.skip_qwen,
        repeat=args.repeat,
        compare_only=args.compare,
    ))
