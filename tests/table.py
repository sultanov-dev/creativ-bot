"""Jadval-testlar: bir xil tekshiruvning ko'p holati bitta testda (yuzlab alohida test o'rniga).

Xato bo'lsa, birinchisida to'xtamaydi: noto'g'ri chiqqan barcha holatlar bitta xabarda ko'rsatiladi.
"""
from collections.abc import Awaitable, Callable, Iterable
from typing import Any


def _args(case: Any) -> tuple:
    return case if isinstance(case, tuple) else (case,)


def check(fn: Callable[..., Any], cases: Iterable[tuple[Any, Any]]) -> None:
    """cases: (argument yoki argumentlar tuple'i, kutilgan natija)."""
    wrong = [(c, want, got) for c, want in cases if (got := fn(*_args(c))) != want]
    assert not wrong, "\n".join(f"{c!r}: kutilgan {want!r}, chiqdi {got!r}" for c, want, got in wrong)


async def acheck(fn: Callable[..., Awaitable[Any]], cases: Iterable[tuple[Any, Any]]) -> None:
    wrong = []
    for c, want in cases:
        got = await fn(*_args(c))
        if got != want:
            wrong.append((c, want, got))
    assert not wrong, "\n".join(f"{c!r}: kutilgan {want!r}, chiqdi {got!r}" for c, want, got in wrong)


def same(fn: Callable[..., Any], inputs: Iterable[Any], want: Any) -> None:
    """Hamma kirish uchun bir xil natija."""
    check(fn, ((i, want) for i in inputs))
