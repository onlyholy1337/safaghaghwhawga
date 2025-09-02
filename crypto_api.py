import aiohttp
from typing import Optional

class CryptoAPI:
    def __init__(self, token: str):
        self.base_url = "https://pay.crypt.bot/api"
        self.headers = {"Crypto-Pay-API-Token": token}

    async def get_me(self):
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{self.base_url}/getMe", headers=self.headers) as response:
                return await response.json()

    async def create_invoice(self, asset: str, amount: float) -> Optional[dict]:
        payload = {
            "asset": asset,
            "amount": amount,
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{self.base_url}/createInvoice", headers=self.headers, json=payload) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("result")
                return None

    async def get_invoices(self, invoice_ids: list[int]) -> Optional[dict]:
        params = {
            "invoice_ids": ",".join(map(str, invoice_ids))
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{self.base_url}/getInvoices", headers=self.headers, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("result")
                return None