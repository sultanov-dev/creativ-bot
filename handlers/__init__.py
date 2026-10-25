from aiogram import Router

from . import admin, anketa, join, start


def get_routers() -> list[Router]:
    return [start.router, join.router, anketa.router, admin.router]
