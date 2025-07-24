"""
NYC Parking Violations API Client - Using Official NYC Open Data API
This replaces web scraping with direct API calls to NYC Open Data
"""

import asyncio
import aiohttp
import logging
from datetime import datetime
from typing import Dict, List, Optional
import json

logger = logging.getLogger(__name__)

class NYCViolationsAPI:
    """Official NYC Open Data API client for parking violations"""
    
    def __init__(self):
        self.base_url = "https://data.cityofnewyork.us/resource/nc67-uf89.json"
        self.app_token = None  # Optional: Register for app token for higher rate limits
        
    async def search_violations(self, license_plate: str, state: str = "NY") -> Dict:
        """
        Search for parking violations using NYC Open Data API
        
        Args:
            license_plate: License plate number
            state: State abbreviation (default: NY)
            
        Returns:
            Dictionary with violation data
        """
        start_time = datetime.now()
        
        logger.info(f"🔍 Searching violations for {license_plate} ({state}) via NYC Open Data API")
        
        result = {
            'license_plate': license_plate.upper(),
            'state': state.upper(),
            'violations': [],
            'total_violations': 0,
            'processing_time': 0,
            'success': False,
            'error': None,
            'debug_info': {
                'api_used': 'NYC Open Data',
                'endpoint': self.base_url
            }
        }
        
        try:
            # Build query URL - NYC Open Data uses direct URL parameters
            url = f"{self.base_url}?plate={license_plate.upper()}"
            
            # Add state filter if not NY (NY is default/most common)
            if state.upper() != "NY":
                url += f"&state={state.upper()}"
            
            # Add app token if available for higher rate limits
            if self.app_token:
                url += f"&$$app_token={self.app_token}"
            
            result['debug_info']['query_url'] = url
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        violations_data = await response.json()
                        
                        # Process and format violations
                        formatted_violations = self._format_violations(violations_data)
                        
                        result.update({
                            'violations': formatted_violations,
                            'total_violations': len(formatted_violations),
                            'success': True,
                            'raw_data': violations_data  # Keep original API response
                        })
                        
                        logger.info(f"✅ API call successful: {len(formatted_violations)} violations found")
                        
                    else:
                        error_text = await response.text()
                        error_msg = f"API returned status {response.status}: {error_text}"
                        result['error'] = error_msg
                        logger.error(f"❌ {error_msg}")
                        
        except Exception as e:
            error_msg = f"API request failed: {str(e)}"
            result['error'] = error_msg
            logger.error(f"❌ {error_msg}")
        
        finally:
            result['processing_time'] = (datetime.now() - start_time).total_seconds()
        
        return result
    
    def _format_violations(self, violations_data: List[Dict]) -> List[Dict]:
        """Format violations data for consistent structure"""
        formatted = []
        
        for violation in violations_data:
            # Extract and format violation data
            formatted_violation = {
                # Basic info
                'plate': violation.get('plate', ''),
                'state': violation.get('state', ''),
                'license_type': violation.get('license_type', ''),
                
                # Violation details
                'summons_number': violation.get('summons_number', ''),
                'violation_code': violation.get('violation', ''),  # This is the description
                'issue_date': violation.get('issue_date', ''),
                'violation_time': violation.get('violation_time', ''),
                'judgment_entry_date': violation.get('judgment_entry_date', ''),
                
                # Financial info
                'fine_amount': self._safe_float(violation.get('fine_amount', 0)),
                'penalty_amount': self._safe_float(violation.get('penalty_amount', 0)),
                'interest_amount': self._safe_float(violation.get('interest_amount', 0)),
                'reduction_amount': self._safe_float(violation.get('reduction_amount', 0)),
                'payment_amount': self._safe_float(violation.get('payment_amount', 0)),
                'amount_due': self._safe_float(violation.get('amount_due', 0)),
                
                # Location info
                'precinct': violation.get('precinct', ''),
                'county': violation.get('county', ''),
                'issuing_agency': violation.get('issuing_agency', ''),
                
                # Additional data
                'summons_image': violation.get('summons_image', {}),
                
                # Status derived from amounts
                'status': self._determine_status(violation),
                
                # Keep original data
                'raw_data': violation
            }
            
            formatted.append(formatted_violation)
        
        return formatted
    
    def _safe_float(self, value) -> float:
        """Safely convert value to float"""
        try:
            return float(value) if value else 0.0
        except (ValueError, TypeError):
            return 0.0
    
    def _determine_status(self, violation: Dict) -> str:
        """Determine violation status based on amounts"""
        amount_due = self._safe_float(violation.get('amount_due', 0))
        payment_amount = self._safe_float(violation.get('payment_amount', 0))
        
        if amount_due <= 0 and payment_amount > 0:
            return "PAID"
        elif amount_due > 0:
            return "OUTSTANDING"
        else:
            return "UNKNOWN"
    
    def get_violation_summary(self, violations: List[Dict]) -> Dict:
        """Get summary statistics for violations"""
        if not violations:
            return {
                'total_violations': 0,
                'total_amount_due': 0.0,
                'paid_violations': 0,
                'outstanding_violations': 0,
                'agencies': [],
                'violation_types': []
            }
        
        total_due = sum(v['amount_due'] for v in violations)
        paid_count = len([v for v in violations if v['status'] == 'PAID'])
        outstanding_count = len([v for v in violations if v['status'] == 'OUTSTANDING'])
        
        agencies = list(set(v['issuing_agency'] for v in violations if v['issuing_agency']))
        violation_types = list(set(v['violation_code'] for v in violations if v['violation_code']))
        
        return {
            'total_violations': len(violations),
            'total_amount_due': total_due,
            'paid_violations': paid_count,
            'outstanding_violations': outstanding_count,
            'agencies': agencies,
            'violation_types': violation_types
        }

# Test function
async def test_api_client():
    """Test the API client"""
    
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    
    client = NYCViolationsAPI()
    
    print("🧪 TESTING NYC VIOLATIONS API CLIENT")
    print("="*60)
    
    # Test with K58ARK
    result = await client.search_violations('K58ARK', 'NY')
    
    print(f"\\n📊 RESULTS FOR K58ARK:")
    print(f"   License Plate: {result['license_plate']}")
    print(f"   State: {result['state']}")
    print(f"   Success: {result['success']}")
    print(f"   Processing Time: {result['processing_time']:.2f}s")
    print(f"   Violations Found: {result['total_violations']}")
    
    if result['success']:
        if result['violations']:
            print(f"\\n🎫 VIOLATIONS:")
            for i, violation in enumerate(result['violations'][:3], 1):
                print(f"\\n   {i}. Summons: {violation['summons_number']}")
                print(f"      Date: {violation['issue_date']}")
                print(f"      Violation: {violation['violation_code']}")
                print(f"      Fine: \${violation['fine_amount']}")
                print(f"      Amount Due: \${violation['amount_due']}")
                print(f"      Status: {violation['status']}")
                print(f"      Agency: {violation['issuing_agency']}")
            
            if len(result['violations']) > 3:
                print(f"\\n   ... and {len(result['violations']) - 3} more violations")
            
            # Show summary
            summary = client.get_violation_summary(result['violations'])
            print(f"\\n📈 SUMMARY:")
            print(f"   Total Amount Due: \${summary['total_amount_due']}")
            print(f"   Paid: {summary['paid_violations']}")
            print(f"   Outstanding: {summary['outstanding_violations']}")
            
        else:
            print("\\n✅ NO VIOLATIONS FOUND (Clean record)")
    else:
        print(f"\\n❌ ERROR: {result['error']}")
    
    print(f"\\n🔍 DEBUG INFO:")
    for key, value in result['debug_info'].items():
        print(f"   {key}: {value}")
    
    return result

if __name__ == "__main__":
    asyncio.run(test_api_client())