# 평가 기준 및 루브릭 정의
# LLM-as-Judge (Claude)가 Qwen 출력을 채점할 때 사용

# 개인 심박존 기준 (DB training_zones 기준)
ZONES = {
    "zone1": (0, 138),
    "zone2": (139, 150),
    "zone3": (151, 162),
    "zone4": (163, 174),
    "zone5": (175, 999),
}

ZONES_DESCRIPTION = """존1 (매우 가벼움): 138bpm 이하
존2 (유산소 기반): 139~150bpm
존3 (유산소 파워): 151~162bpm
존4 (무산소 역치): 163~174bpm
존5 (최대 강도):   175bpm 이상"""

# 평가 기준 5개 정의
CRITERIA = {
    "accuracy": {
        "name": "정확성",
        "description": "심박존 판단이 개인 존 기준으로 정확한가",
        "rubric": """5점: 평균/최고 심박을 존 기준으로 정확히 언급하고 올바른 존으로 분류
4점: 존 판단은 맞지만 근거 설명 부족하거나 수치 언급 없음
3점: 존을 모호하게 표현하거나 범위 불명확
2점: 존 판단 1단계 오류 (예: 존4를 존3으로)
1점: 존 판단 심각한 오류 (예: 168bpm을 "존2 내에서 안정적"으로 분석)""",
    },
    "specificity": {
        "name": "구체성",
        "description": "실제 수치를 인용하며 분석했는가",
        "rubric": """5점: 페이스, 심박, 거리 등 수치를 구체적으로 인용하며 분석
4점: 수치 일부 언급, 대부분 구체적
3점: 수치와 모호한 서술이 혼재
2점: 수치 거의 없음, 대부분 막연한 서술
1점: 수치 전혀 없음, "잘 하셨습니다" 수준""",
    },
    "personalization": {
        "name": "개인화",
        "description": "이 사람의 목표와 상황을 반영했는가",
        "rubric": """5점: 하프마라톤/10km PB 목표와 연결, 현재 상황에 맞는 구체적 조언
4점: 목표는 언급하나 구체적 연결 부족
3점: 일반적 러닝 조언
2점: 목표 언급 없음, 누구에게나 해당하는 피드백
1점: 완전히 일반적, 개인화 요소 없음""",
    },
    "practicality": {
        "name": "실용성",
        "description": "내일 훈련 추천이 실행 가능하고 존 기준에 맞는가",
        "rubric": """5점: 훈련 종류·거리·페이스·목표 심박이 모두 존 기준에 맞게 구체적
4점: 대부분 구체적이나 일부 항목 누락 또는 미세한 존 불일치
3점: 종류와 거리만 언급, 페이스/심박 기준 없음
2점: "가볍게 뛰세요" 수준의 모호한 추천
1점: 추천 자체가 없거나 실행 불가능한 내용""",
    },
    "korean_quality": {
        "name": "한국어 품질",
        "description": "자연스러운 러닝 용어를 사용했는가",
        "rubric": """5점: 자연스러운 러닝 용어 (존2 조깅, 템포런, LSD 등) 올바르게 사용
4점: 대체로 자연스럽지만 약간 어색한 표현 있음
3점: 이해는 가능하지만 어색한 표현 다수
2점: 직역 투의 어색한 표현 다수
1점: "병원동력주행" 같은 명백히 잘못된 번역 용어 사용""",
    },
}

# Claude에게 전달할 평가 프롬프트 템플릿
JUDGE_PROMPT_TEMPLATE = """당신은 러닝 코칭 AI의 출력을 평가하는 전문 심사위원입니다.
편향 없이 루브릭 기준에만 따라 채점하세요.

## 평가 대상 운동 데이터
{activity_data}

## 개인 심박존 기준 (반드시 이 기준으로 정확성 판단)
{zones_description}

## AI 코치 출력 (평가 대상)
{llm_output}

## 평가 기준 및 루브릭

### 1. 정확성 (Accuracy)
{accuracy_rubric}

### 2. 구체성 (Specificity)
{specificity_rubric}

### 3. 개인화 (Personalization)
{personalization_rubric}

### 4. 실용성 (Practicality)
{practicality_rubric}

### 5. 한국어 품질 (Korean Quality)
{korean_quality_rubric}

## 응답 형식
반드시 아래 JSON으로만 응답하세요. 다른 텍스트는 포함하지 마세요:

{{
  "accuracy": {{"score": 1~5점, "reason": "판단 이유 한 문장"}},
  "specificity": {{"score": 1~5점, "reason": "판단 이유 한 문장"}},
  "personalization": {{"score": 1~5점, "reason": "판단 이유 한 문장"}},
  "practicality": {{"score": 1~5점, "reason": "판단 이유 한 문장"}},
  "korean_quality": {{"score": 1~5점, "reason": "판단 이유 한 문장"}},
  "total": 5개 점수의 합계
}}"""


def build_judge_prompt(activity_data: str, llm_output: str) -> str:
    """평가 프롬프트 생성"""
    return JUDGE_PROMPT_TEMPLATE.format(
        activity_data=activity_data,
        zones_description=ZONES_DESCRIPTION,
        llm_output=llm_output,
        accuracy_rubric=CRITERIA["accuracy"]["rubric"],
        specificity_rubric=CRITERIA["specificity"]["rubric"],
        personalization_rubric=CRITERIA["personalization"]["rubric"],
        practicality_rubric=CRITERIA["practicality"]["rubric"],
        korean_quality_rubric=CRITERIA["korean_quality"]["rubric"],
    )


def get_expected_zone(avg_heartrate: float) -> str:
    """평균 심박수로 정답 존 반환"""
    if avg_heartrate <= 138:
        return "존1"
    elif avg_heartrate <= 150:
        return "존2"
    elif avg_heartrate <= 162:
        return "존3"
    elif avg_heartrate <= 174:
        return "존4"
    else:
        return "존5"
