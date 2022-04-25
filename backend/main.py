# coding:utf-8
from time import time
import json
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from starlette.middleware.cors import CORSMiddleware

app = FastAPI()
origins = ["*"]


app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"])


class Game:
    def __init__(self, title, question, selections: list[str], start_timestamp_msec=0,
                 duration_msec=0, status="finished"):
        self.title = title
        self.question = question
        self.selections = selections
        self.allocations = []
        for i in range(len(self.selections)):
            self.allocations.append(set())
        # status: waiting, started, finished
        self.status = status
        self.start_timestamp_msec = start_timestamp_msec
        self.duration_msec = duration_msec


game = Game("测试用例", "门票先花掉2元：\n(1)如果过半人选A而你也选A,那你将得到1元。\n(2)如果过半人选A而你选B,那你将得到6元。\n(3)如果过半人选B,则选B的扣掉2元，选A的得到4元。",
            ["A", "B"], 1650816000000, 69400000, "started")

chats = []


class SubmitItem(BaseModel):
    selection: int
    timestamp: int
    user_id: str


class GameHttp(BaseModel):
    title: str
    question: str
    selections: list[str]
    start_timestamp_msec: int
    duration_msec: int


def update_game_status(game):
    if time() * 1000 - game.start_timestamp_msec > game.duration_msec:
        game.status = "finished"
    elif game.status == "waiting":
        game.status = "started"


@app.post("/new_game")
async def new_game(new_game: GameHttp):
    global game, chats
    game = Game(new_game.title, new_game.question, new_game.selections, new_game.start_timestamp_msec,
                new_game.duration_msec, "started")
    update_game_status(game)
    chats = []
    return game


@app.post("/submits")
async def submit(submit: SubmitItem):
    update_game_status(game)
    print(f"{submit.user_id} submitted {submit.selection} at {submit.timestamp}")
    if game.status != "started":
        return {"status": f"invalid operation, game is {game.status}"}
    dup_flag = False
    for allocation in game.allocations:
        if submit.user_id in allocation:
            dup_flag = True
    if dup_flag:
        return {"status": "duplicate"}
    game.allocations[submit.selection].add(submit.user_id)
    print(game.allocations)
    return {"status": "ok"}


@app.get("/submits")
async def get_submits() -> Game:
    update_game_status(game)
    return game


class ConnectionManager:
    def __init__(self):
        # 存放激活的ws连接对象
        self.active_connections: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        # 等待连接
        await ws.accept()
        # 存储ws连接对象
        self.active_connections.append(ws)

    def disconnect(self, ws: WebSocket):
        # 关闭时 移除ws对象
        self.active_connections.remove(ws)

    @staticmethod
    async def send_personal_message(message: str, ws: WebSocket):
        # 发送个人消息
        await ws.send_text(message)

    async def broadcast(self, message: str):
        # 广播消息
        for connection in self.active_connections:
            await connection.send_text(message)


manager = ConnectionManager()


@app.websocket("/ws/{user}")
async def websocket_endpoint(websocket: WebSocket, user: str):

    await manager.connect(websocket)

    await manager.broadcast(f"用户{user}进入聊天室")

    try:
        while True:
            data = await websocket.receive_text()
            await manager.send_personal_message(f"你说了: {data}", websocket)
            await manager.broadcast(f"用户:{user} 说: {data}")

    except WebSocketDisconnect:
        manager.disconnect(websocket)
        await manager.broadcast(f"用户-{user}-离开")


@app.websocket("/chat/{user}")
async def chat(websocket: WebSocket, user: str):
    await manager.connect(websocket)
    await manager.send_personal_message(json.dumps({"type": "init", "chats": chats}), websocket)
    await manager.broadcast(json.dumps({"type": "enter", "user": user, "message": f"用户{user}进入聊天室"}))
    try:
        while True:
            data = await websocket.receive_text()
            chats.append({"user": user, "message": data})
            await manager.broadcast(json.dumps({"type": "message", "user": user, "message": data}))

    except WebSocketDisconnect:
        manager.disconnect(websocket)
        await manager.broadcast(json.dumps({"type": "exit", "user": user, "message": f"用户{user}离开聊天室"}))
