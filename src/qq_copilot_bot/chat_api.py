#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# @Date    : 2026/03/05 21:04:37
# @Author  : Kan HUANG
# @Desc    : None

import requests

url = "http://127.0.0.1:8000/chat"


async def chat_api_session(model_name: str, messages: list) -> dict:
    """
    :param model_name: str
    :param messages: list of dict
    :return: dict
    """
    data = {
        "model_name": model_name,
        "messages": messages,
    }
    resp = requests.post(url, json=data)
    if resp.status_code != 200:
        raise Exception(f"chat api error, status code: {resp.status_code}")
    else:
        return resp.json()
