"""自定义异常：区分「业务错误」与「系统错误」，供全局处理器统一转成标准响应体。

- BusinessException：可预期的业务错误（资源不存在、唯一性冲突等）。
  message 面向用户（中文、可直接展示），HTTP 状态码通常为 4xx。
- SystemException：不可预期的系统错误（内部故障、依赖异常等）。
  对外只给通用文案，真实原因记入 detail 并写日志，供后端定位，HTTP 状态码 5xx。
"""


class AppException(Exception):
    """异常基类：统一携带 http_status / code / message / detail。

    code 复用 HTTP 状态码，因此 code == http_status。
    detail 仅用于后端定位，不面向用户，禁止写入敏感信息。
    """

    http_status: int = 500
    default_message: str = "服务异常"

    def __init__(
        self,
        message: str | None = None,
        *,
        detail: str | None = None,
        http_status: int | None = None,
    ) -> None:
        # 允许在抛出点覆盖默认状态码（如业务错误里区分 404 / 409）
        if http_status is not None:
            self.http_status = http_status
        self.message = message or self.default_message
        self.detail = detail

        """
          `super()` 的指向:
          - 在该方法中，`super()` 指向当前类的父类，即 `Exception`。
          - 也就是说，它用于调用父类的 `__init__` 方法，以完成异常对象的标准初始化流程。
        """
        super().__init__(self.message)

    @property
    def code(self) -> int:
        """code 复用 HTTP 状态码。"""
        """返回当前异常对象对应的错误码。
        
          该属性使用 @property 装饰器，将一个方法转换为“只读属性”，
          使调用者可以像访问属性一样使用 obj.code，而不必显式调用 obj.code()。
      
          在这里，code 直接复用 HTTP 状态码作为错误代码，这样可以：
          - 与 HTTP 响应状态保持一致；
          - 方便在接口层统一返回和处理错误；
          - 避免额外维护一套业务错误码与 HTTP 状态码的映射逻辑。
      
          @property 的核心作用是：让方法表现得像属性，提升代码可读性和封装性。
        """
        return self.http_status


class BusinessException(AppException):
    """业务错误：可预期，message 直接面向用户展示。"""

    http_status = 400
    default_message = "业务处理失败"


class SystemException(AppException):
    """系统错误：不可预期，对外通用文案，细节走日志。"""

    http_status = 500
    default_message = "系统内部错误，请稍后重试"
