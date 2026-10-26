from aiogram import Router

from . import admin, ai, anketa, errors, group, join, reason, start, vote


def get_routers() -> list[Router]:
    return [
        errors.router,
        start.router,
        join.router,
        anketa.router,
        admin.router,
        vote.router,
        reason.router,
        group.router,
        ai.router,
    ]
