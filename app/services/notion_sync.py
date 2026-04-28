"""
Notion → DB 동기화 서비스 (P1-03)

Notion의 코치 설정(목표, 프로필)을 읽어 로컬 DB에 동기화.
주간 코치 실행 시 호출 → Notion 변경사항이 자동 반영됨.

Notion DB 구조:
  Goals DB:
    이름(title), 이벤트(select: 10km/half/full), 목표기록(text: HH:MM:SS),
    우선순위(select: primary/secondary), 대회명(text), 대회날짜(date),
    대회확정(checkbox), 주당훈련일수(number), 주당최대거리(number),
    부상메모(text), 상태(select: active/achieved/abandoned)

  Profile DB:
    날짜(date), 체중(number), 키(number)
"""

import httpx
from datetime import datetime

import app.config as config
from app.models.database import upsert_goal, save_profile


NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {config.NOTION_API_KEY}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def _get_text(prop: dict) -> str:
    """Notion rich_text / title 프로퍼티에서 텍스트 추출"""
    items = prop.get("rich_text") or prop.get("title") or []
    return "".join(i.get("plain_text", "") for i in items).strip()


def _get_select(prop: dict) -> str:
    """Notion select 프로퍼티에서 값 추출"""
    sel = prop.get("select")
    return sel.get("name", "") if sel else ""


def _get_number(prop: dict) -> float | None:
    return prop.get("number")


def _get_date(prop: dict) -> str | None:
    d = prop.get("date")
    return d.get("start") if d else None


def _get_checkbox(prop: dict) -> bool:
    return prop.get("checkbox", False)


def _parse_time_to_sec(time_str: str) -> int | None:
    """HH:MM:SS 또는 MM:SS → 초 변환"""
    if not time_str:
        return None
    parts = time_str.strip().split(":")
    try:
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        elif len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
    except ValueError:
        return None
    return None


async def sync_goals_from_notion(user_id: int = 1) -> int:
    """
    Notion Goals DB → 로컬 goals 테이블 동기화
    반환: 동기화된 목표 수
    """
    if not config.NOTION_GOALS_DB_ID:
        print("NOTION_GOALS_DB_ID 미설정 → 목표 동기화 스킵")
        return 0

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            f"{NOTION_API}/databases/{config.NOTION_GOALS_DB_ID}/query",
            headers=_headers(),
            json={"filter": {"property": "상태", "select": {"equals": "active"}}},
        )

    if resp.status_code != 200:
        print(f"Notion Goals 조회 실패: {resp.status_code} {resp.text[:200]}")
        return 0

    pages = resp.json().get("results", [])
    synced = 0

    for page in pages:
        props = page.get("properties", {})
        try:
            event_type = _get_select(props.get("이벤트", {}))
            priority = _get_select(props.get("우선순위", {})) or "primary"
            time_str = _get_text(props.get("목표기록", {}))
            target_time_sec = _parse_time_to_sec(time_str)
            target_date = _get_date(props.get("대회날짜", {}))
            race_name = _get_text(props.get("대회명", {})) or None
            race_confirmed = _get_checkbox(props.get("대회확정", {}))
            weekly_days = _get_number(props.get("주당훈련일수", {})) or 4
            max_weekly_km = _get_number(props.get("주당최대거리", {})) or 30
            injury_notes = _get_text(props.get("부상메모", {})) or None

            if not event_type or not target_time_sec:
                continue

            upsert_goal(
                user_id=user_id,
                priority=priority,
                event_type=event_type,
                target_time_sec=int(target_time_sec),
                target_date=target_date,
                race_name=race_name,
                race_confirmed=race_confirmed,
                weekly_days_available=int(weekly_days),
                max_weekly_km=float(max_weekly_km),
                injury_notes=injury_notes,
            )
            synced += 1
        except Exception as e:
            print(f"목표 파싱 실패: {e}")
            continue

    print(f"Notion 목표 동기화 완료: {synced}개")
    return synced


async def sync_profile_from_notion(user_id: int = 1) -> bool:
    """
    Notion Profile DB의 최신 체중/키 → 로컬 profile 테이블 저장
    """
    if not config.NOTION_PROFILE_DB_ID:
        print("NOTION_PROFILE_DB_ID 미설정 → 프로필 동기화 스킵")
        return False

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            f"{NOTION_API}/databases/{config.NOTION_PROFILE_DB_ID}/query",
            headers=_headers(),
            json={"sorts": [{"property": "날짜", "direction": "descending"}], "page_size": 1},
        )

    if resp.status_code != 200:
        print(f"Notion Profile 조회 실패: {resp.status_code}")
        return False

    pages = resp.json().get("results", [])
    if not pages:
        return False

    props = pages[0].get("properties", {})
    weight_kg = _get_number(props.get("체중", {}))
    height_cm = _get_number(props.get("키", {}))

    if weight_kg:
        save_profile(user_id=user_id, weight_kg=weight_kg, height_cm=height_cm)
        print(f"Notion 프로필 동기화 완료: {weight_kg}kg")
        return True

    return False


async def sync_all(user_id: int = 1) -> None:
    """목표 + 프로필 한번에 동기화"""
    await sync_goals_from_notion(user_id)
    await sync_profile_from_notion(user_id)
