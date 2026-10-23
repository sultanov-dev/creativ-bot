from aiogram import Router

from . import anketa, join, start


def get_routers() -> list[Router]:
    return [start.router, join.router, anketa.router]
