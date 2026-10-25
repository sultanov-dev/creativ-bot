from aiogram import Router

from . import admin, anketa, group, join, reason, start, vote


def get_routers() -> list[Router]:
    return [
        start.router,
        join.router,
        anketa.router,
        admin.router,
        vote.router,
        reason.router,
        group.router,
    ]
