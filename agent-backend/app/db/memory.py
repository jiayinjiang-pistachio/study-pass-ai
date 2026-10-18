"""数据库层：用内存字典模拟一张 users 表，不连接真实数据库。

约定：
- 上层只能通过本模块的函数读写，禁止直接访问内部字典；
- 对外一律返回记录副本，避免调用方意外改动内存中的数据；
- 进程重启即清空，仅用于开发 / 演示。
"""

from typing import Any

# 内存「表」：id -> 用户记录（记录内含 password 哈希）
_users: dict[int, dict[str, Any]] = {}
_auto_increment = 0  # 自增主键计数器


def _next_id() -> int:
    """生成下一个自增主键。"""
    global _auto_increment
    _auto_increment += 1
    return _auto_increment


def insert(record: dict[str, Any]) -> dict[str, Any]:
    """插入一条记录，自动分配 id，返回完整记录副本。"""
    user_id = _next_id()
    row = {"id": user_id, **record}
    _users[user_id] = row
    return dict(row)


def get(user_id: int) -> dict[str, Any] | None:
    """按 id 查询，未找到返回 None。"""
    row = _users.get(user_id)
    return dict(row) if row else None


def list_all() -> list[dict[str, Any]]:
    """返回内存中的全部记录，并按 id 升序排列后返回。

    语法说明：
    - `def list_all() -> list[dict[str, Any]]`：
      定义一个无参数函数，返回值类型为 `list[dict[str, Any]]`，表示返回一个列表，
      列表中的每一项都是一个字典，字典里存放一条记录数据。
    - `sorted(_users.values(), key=lambda r: r["id"])`：
      对 `_users.values()` 中的所有记录做排序，`key=lambda r: r["id"]` 表示按每条记录的
      `"id"` 字段进行升序排序。
    - `[dict(row) for row in ...]`：
      这是列表推导式，遍历排序后的每一条记录，并用 `dict(row)` 把记录转换成普通字典对象。
      这样返回的结果可以直接被业务代码使用，也更容易序列化输出。

    作用：
    - 获取当前内存中所有用户/记录数据。
    - 统一按 ID 升序返回，方便前端展示、日志输出、接口响应或后续处理。
    - 返回的数据结构是可读的 `list[dict]`，便于循环遍历和转换为 JSON 等格式。
    """
    """返回全部记录（按 id 升序）。"""
    return [dict(row) for row in sorted(_users.values(), key=lambda r: r["id"])]


def update(user_id: int, fields: dict[str, Any]) -> dict[str, Any] | None:
    """按 id 局部更新字段，未找到返回 None。"""
    row = _users.get(user_id)
    if row is None:
        return None
    row.update(fields)
    return dict(row)


def delete(user_id: int) -> bool:
    """按 id 删除，返回是否删除成功。"""
    return _users.pop(user_id, None) is not None


def find_by_username(username: str) -> dict[str, Any] | None:
    """按用户名精确查询（供业务层做唯一性校验）。"""
    return next((dict(r) for r in _users.values() if r["username"] == username), None)


def find_by_email(email: str) -> dict[str, Any] | None:
    """
    按邮箱精确查询用户，供业务层执行唯一性校验。

    返回值:
      dict[str, Any] | None: 返回第一个匹配邮箱的用户字典；若未找到，则返回 None。

    说明:
      这里使用了内置函数 `next()`，其语法为：

        next(iterator, default=None)

      参数说明:
        - iterator: 可迭代对象或迭代器，例如生成器表达式。
        - default: 可选参数；当 iterator 中没有可取元素时，返回该默认值。

      作用:
        - 从迭代器中取出下一个元素。
        - 常用于“取第一个匹配项”的场景。
        - 若没有元素可取，则返回默认值，而不是抛出 `StopIteration` 异常。

      这段逻辑的含义是：
        依次遍历 `_users.values()` 中的所有用户记录，筛选出 `email` 等于目标值的记录；
        然后用 `next(...)` 取出第一个匹配项并转换为普通字典。
        如果没有找到任何匹配项，则返回 `None`。

      这样既能保证查询结果的唯一性，又能在未命中时安全返回空值，适合业务层唯一性校验。
    """
    """按邮箱精确查询（供业务层做唯一性校验）。"""
    return next((dict(r) for r in _users.values() if r["email"] == email), None)
