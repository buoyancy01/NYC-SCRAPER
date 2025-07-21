import aiohttp
import asyncio

class CaptchaClient:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "http://2captcha.com"
    
    async def solve_recaptcha(self, site_key: str, page_url: str) -> str:
        """Solve reCAPTCHA v2"""
        # Submit CAPTCHA
        submit_url = f"{self.base_url}/in.php"
        submit_data = {
            'key': self.api_key,
            'method': 'userrecaptcha',
            'googlekey': site_key,
            'pageurl': page_url
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(submit_url, data=submit_data) as response:
                result = await response.text()
                if not result.startswith('OK|'):
                    raise Exception(f"2captcha submit failed: {result}")
                
                captcha_id = result.split('|')[1]
            
            # Wait for solution
            result_url = f"{self.base_url}/res.php"
            for _ in range(60):  # 5 minutes max
                await asyncio.sleep(5)
                
                async with session.get(result_url, params={'key': self.api_key, 'action': 'get', 'id': captcha_id}) as response:
                    result = await response.text()
                    
                    if result == 'CAPCHA_NOT_READY':
                        continue
                    elif result.startswith('OK|'):
                        return result.split('|')[1]
                    else:
                        raise Exception(f"2captcha solve failed: {result}")
            
            raise Exception("CAPTCHA solving timeout")