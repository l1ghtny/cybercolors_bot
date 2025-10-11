from fastapi import APIRouter

auth = APIRouter(prefix="/auth", tags=["authentication"])


@auth.post('/login')
async def login():
    return 'login'


@auth.post('/logout')
async def logout():
    return 'logout'