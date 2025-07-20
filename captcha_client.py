import requests
import time
import logging
from typing import Optional, Dict, Any
import base64

logger = logging.getLogger(__name__)

class TwoCaptchaClient:
    """Client for 2captcha CAPTCHA solving service"""
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "http://2captcha.com"
        self.session = requests.Session()
    
    async def solve_recaptcha_v2(self, site_key: str, page_url: str) -> Optional[str]:
        """
        Solve reCAPTCHA v2
        """
        try:
            # Submit CAPTCHA for solving
            submit_response = self._submit_recaptcha_v2(site_key, page_url)
            if not submit_response:
                return None
            
            captcha_id = submit_response
            logger.info(f"reCAPTCHA v2 submitted with ID: {captcha_id}")
            
            # Wait and get result
            return await self._get_captcha_result(captcha_id)
            
        except Exception as e:
            logger.error(f"Error solving reCAPTCHA v2: {e}")
            return None
    
    async def solve_image_captcha(self, image_data: bytes) -> Optional[str]:
        """
        Solve image-based CAPTCHA
        """
        try:
            # Encode image to base64
            image_b64 = base64.b64encode(image_data).decode('utf-8')
            
            # Submit image CAPTCHA
            submit_data = {
                'key': self.api_key,
                'method': 'base64',
                'body': image_b64
            }
            
            response = self.session.post(f"{self.base_url}/in.php", data=submit_data)
            result = response.text.strip()
            
            if result.startswith('OK|'):
                captcha_id = result.split('|')[1]
                logger.info(f"Image CAPTCHA submitted with ID: {captcha_id}")
                
                # Wait and get result
                return await self._get_captcha_result(captcha_id)
            else:
                logger.error(f"Failed to submit image CAPTCHA: {result}")
                return None
                
        except Exception as e:
            logger.error(f"Error solving image CAPTCHA: {e}")
            return None
    
    def _submit_recaptcha_v2(self, site_key: str, page_url: str) -> Optional[str]:
        """Submit reCAPTCHA v2 for solving"""
        try:
            submit_data = {
                'key': self.api_key,
                'method': 'userrecaptcha',
                'googlekey': site_key,
                'pageurl': page_url
            }
            
            response = self.session.post(f"{self.base_url}/in.php", data=submit_data)
            result = response.text.strip()
            
            if result.startswith('OK|'):
                return result.split('|')[1]
            else:
                logger.error(f"Failed to submit reCAPTCHA v2: {result}")
                return None
                
        except Exception as e:
            logger.error(f"Error submitting reCAPTCHA v2: {e}")
            return None
    
    async def _get_captcha_result(self, captcha_id: str, max_attempts: int = 30) -> Optional[str]:
        """Get CAPTCHA solution result"""
        for attempt in range(max_attempts):
            try:
                # Wait before checking (2captcha needs time to solve)
                await self._async_sleep(5)
                
                check_data = {
                    'key': self.api_key,
                    'action': 'get',
                    'id': captcha_id
                }
                
                response = self.session.get(f"{self.base_url}/res.php", params=check_data)
                result = response.text.strip()
                
                if result == 'CAPCHA_NOT_READY':
                    logger.info(f"CAPTCHA {captcha_id} not ready, attempt {attempt + 1}/{max_attempts}")
                    continue
                elif result.startswith('OK|'):
                    solution = result.split('|')[1]
                    logger.info(f"CAPTCHA {captcha_id} solved successfully")
                    return solution
                else:
                    logger.error(f"Error getting CAPTCHA result: {result}")
                    return None
                    
            except Exception as e:
                logger.error(f"Error checking CAPTCHA result: {e}")
                continue
        
        logger.error(f"CAPTCHA {captcha_id} solving timed out after {max_attempts} attempts")
        return None
    
    async def _async_sleep(self, seconds: int):
        """Async sleep helper"""
        import asyncio
        await asyncio.sleep(seconds)
    
    def get_balance(self) -> Optional[float]:
        """Get account balance"""
        try:
            response = self.session.get(f"{self.base_url}/res.php", params={
                'key': self.api_key,
                'action': 'getbalance'
            })
            
            balance_str = response.text.strip()
            if balance_str.replace('.', '').isdigit():
                return float(balance_str)
            else:
                logger.error(f"Error getting balance: {balance_str}")
                return None
                
        except Exception as e:
            logger.error(f"Error getting balance: {e}")
            return None