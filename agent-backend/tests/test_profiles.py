"""用户背景资料 CRUD 接口测试。

覆盖：鉴权、创建 / 查询 / 局部更新 / 删除、重复创建 409、资料不存在 404、
字段校验 422。资料随测试用户级联清理（外键 ON DELETE CASCADE）。
"""

import httpx

BASE = "/api/profiles"


async def test_profiles_require_login(client: httpx.AsyncClient) -> None:
    """未携带令牌 → 401。"""
    resp = await client.get(f"{BASE}/me")
    assert resp.status_code == 401


async def test_profile_crud_flow(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    """创建 → 查询 → 局部更新 → 删除完整链路。"""
    payload = {
        "target_job": "后端工程师",
        "years_experience": 3,
        "target_level": "P6",
        "target_skills": ["Python", "MySQL"],
        "weak_topics": ["分布式"],
    }

    resp = await client.post(BASE, headers=auth_headers, json=payload)
    assert resp.status_code == 200, resp.text
    created = resp.json()["data"]
    assert created["target_job"] == "后端工程师"
    assert created["target_skills"] == ["Python", "MySQL"]
    assert created["created_at"] > 0
    assert "user_id" not in created

    resp = await client.get(f"{BASE}/me", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["id"] == created["id"]

    # 只更新显式传入的字段，其余保持原值
    resp = await client.put(
        f"{BASE}/me", headers=auth_headers, json={"target_level": "P7"}
    )
    assert resp.status_code == 200, resp.text
    updated = resp.json()["data"]
    assert updated["target_level"] == "P7"
    assert updated["target_job"] == "后端工程师"
    assert updated["years_experience"] == 3

    resp = await client.delete(f"{BASE}/me", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"] is None

    resp = await client.get(f"{BASE}/me", headers=auth_headers)
    assert resp.status_code == 404


async def test_create_profile_conflict(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    """一人一份资料，重复创建 → 409。"""
    assert (await client.post(BASE, headers=auth_headers, json={})).status_code == 200

    resp = await client.post(BASE, headers=auth_headers, json={"target_job": "前端"})
    assert resp.status_code == 409


async def test_profile_missing_404(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    """未填写资料时查询 / 更新 / 删除均 404。"""
    assert (await client.get(f"{BASE}/me", headers=auth_headers)).status_code == 404
    assert (
        await client.put(
            f"{BASE}/me", headers=auth_headers, json={"target_job": "前端"}
        )
    ).status_code == 404
    assert (await client.delete(f"{BASE}/me", headers=auth_headers)).status_code == 404


async def test_profile_validation(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    """年限为负、技能超过 20 项或单项超过 50 字 → 422。"""
    resp = await client.post(
        BASE, headers=auth_headers, json={"years_experience": -1}
    )
    assert resp.status_code == 422

    resp = await client.post(
        BASE, headers=auth_headers, json={"target_skills": ["skill"] * 21}
    )
    assert resp.status_code == 422

    resp = await client.post(
        BASE, headers=auth_headers, json={"target_skills": ["x" * 51]}
    )
    assert resp.status_code == 422
