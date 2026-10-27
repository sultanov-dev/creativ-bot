from aiogram import Router

from . import ads, admin, ai, anketa, decision, errors, group, join, profile, reason, start, vote


def get_routers() -> list[Router]:
    return [
        errors.router,
        start.router,
        join.router,
        profile.router,
        anketa.router,
        admin.router,
        vote.router,
        decision.router,
        reason.router,
        group.router,
        group.strangers,
        ads.router,
        ai.router,
    ]
