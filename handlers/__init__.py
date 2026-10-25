from aiogram import Router

from . import admin, anketa, join, start, vote


def get_routers() -> list[Router]:
    return [start.router, join.router, anketa.router, admin.router, vote.router]
