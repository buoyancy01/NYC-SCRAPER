import os
import time
import requests
import logging
from typing import Optional

logger = logging.getLogger(__name__)

class CaptchaClient:
    """Client for solving CAPTCHAs using external service"""
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get('CAPTCHA_API_KEY')
        self.base_url = "http://2captcha.com"  # Example service
        
    def solve_image_captcha(self, image_data: bytes) -> Optional[str]:
        """
        Solve image-based CAPTCHA
        
        Args:
            image_data: Binary image data of the CAPTCHA
            
        Returns:
            Solved CAPTCHA text or None if failed
        """
        if not self.api_key:
            logger.warning("No CAPTCHA API key provided")
            return None
            
        try:
            # Submit CAPTCHA
            submit_response = requests.post(
                f"{self.base_url}/in.php",
                data={
                    'method': 'base64',
                    'key': self.api_key,
                    'body': image_data
                },
                timeout=30
            )
            
            if submit_response.text.startswith('OK|'):
                captcha_id = submit_response.text.split('|')[1]
                
                # Poll for result
                for _ in range(30):  # Wait up to 5 minutes
                    time.sleep(10)
                    
                    result_response = requests.get(
                        f"{self.base_url}/res.php",
                        params={
                            'key': self.api_key,
                            'action': 'get',
                            'id': captcha_id
                        },
                        timeout=30
                    )
                    
                    if result_response.text == 'CAPCHA_NOT_READY':
                        continue
                    elif result_response.text.startswith('OK|'):
                        return result_response.text.split('|')[1]
                    else:
                        logger.error(f"CAPTCHA solving failed: {result_response.text}")
                        return None
                        
            else:
                logger.error(f"CAPTCHA submission failed: {submit_response.text}")
                return None
                
        except Exception as e:
            logger.error(f"Error solving CAPTCHA: {e}")
            return None
            
        return None
    
    def solve_recaptcha(self, site_key: str, page_url: str) -> Optional[str]:
        """
        Solve reCAPTCHA
        
        Args:
            site_key: reCAPTCHA site key
            page_url: URL of the page with reCAPTCHA
            
        Returns:
            reCAPTCHA solution token or None if failed
        """
        if not self.api_key:
            logger.warning("No CAPTCHA API key provided")
            return None
            
        try:
            # Submit reCAPTCHA
            submit_response = requests.post(
                f"{self.base_url}/in.php",
                data={
                    'method': 'userrecaptcha',
                    'googlekey': site_key,
                    'key': self.api_key,
                    'pageurl': page_url
                },
                timeout=30
            )
            
            if submit_response.text.startswith('OK|'):
                captcha_id = submit_response.text.split('|')[1]
                
                # Poll for result
                for _ in range(60):  # Wait up to 10 minutes for reCAPTCHA
                    time.sleep(10)
                    
                    result_response = requests.get(
                        f"{self.base_url}/res.php",
                        params={
                            'key': self.api_key,
                            'action': 'get',
                            'id': captcha_id
                        },
                        timeout=30
                    )
                    
                    if result_response.text == 'CAPCHA_NOT_READY':
                        continue
                    elif result_response.text.startswith('OK|'):
                        return result_response.text.split('|')[1]
                    else:
                        logger.error(f"reCAPTCHA solving failed: {result_response.text}")
                        return None
                        
            else:
                logger.error(f"reCAPTCHA submission failed: {submit_response.text}")
                return None
                
        except Exception as e:
            logger.error(f"Error solving reCAPTCHA: {e}")
            return None
            
        return None