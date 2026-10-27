from aiogram import Router

from . import ads, admin, ai, anketa, creator, errors, group, join, profile, reason, start, vote


def get_routers() -> list[Router]:
    return [
        errors.router,
        start.router,
        join.router,
        profile.router,
        anketa.router,
        admin.router,
        vote.router,
        creator.router,
        reason.router,
        group.router,
        group.strangers,
        ads.router,
        ai.router,
    ]
