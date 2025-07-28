"""
Proxy detection service module
"""
import asyncio
import time
from typing import Dict, List, Optional
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel

from app.log.logger import get_config_routes_logger

logger = get_config_routes_logger()


class ProxyCheckResult(BaseModel):
    """Proxy check result model"""
    proxy: str
    is_available: bool
    response_time: Optional[float] = None
    error_message: Optional[str] = None
    checked_at: float


class ProxyCheckService:
    """Proxy detection service class"""
    
    # Target URL for checking
    CHECK_URL = "https://www.google.com"
    # Timeout in seconds
    TIMEOUT_SECONDS = 10
    # Cache duration in seconds
    CACHE_DURATION = 10  # 10s
    
    def __init__(self):
        self._cache: Dict[str, ProxyCheckResult] = {}
    
    def _is_valid_proxy_format(self, proxy: str) -> bool:
        """Validate proxy format"""
        try:
            parsed = urlparse(proxy)
            return parsed.scheme in ['http', 'https', 'socks5'] and parsed.hostname
        except Exception:
            return False
    
    def _get_cached_result(self, proxy: str) -> Optional[ProxyCheckResult]:
        """Get cached check result"""
        if proxy in self._cache:
            result = self._cache[proxy]
            # Check if cache is expired
            if time.time() - result.checked_at < self.CACHE_DURATION:
                logger.debug(f"Using cached proxy check result: {proxy}")
                return result
            else:
                # Remove expired cache
                del self._cache[proxy]
        return None
    
    def _cache_result(self, result: ProxyCheckResult) -> None:
        """Cache check result"""
        self._cache[result.proxy] = result
    
    async def check_single_proxy(self, proxy: str, use_cache: bool = True) -> ProxyCheckResult:
        """
        Check if a single proxy is available
        
        Args:
            proxy: Proxy address in format like http://host:port or socks5://host:port
            use_cache: Whether to use cached results
            
        Returns:
            ProxyCheckResult: Check result
        """
        # Check cache first
        if use_cache:
            cached = self._get_cached_result(proxy)
            if cached:
                return cached
        
        # Validate proxy format
        if not self._is_valid_proxy_format(proxy):
            result = ProxyCheckResult(
                proxy=proxy,
                is_available=False,
                error_message="Invalid proxy format",
                checked_at=time.time()
            )
            self._cache_result(result)
            return result
        
        # Perform check
        start_time = time.time()
        try:
            logger.info(f"Starting proxy check: {proxy}")
            
            timeout = httpx.Timeout(self.TIMEOUT_SECONDS, read=self.TIMEOUT_SECONDS)
            async with httpx.AsyncClient(timeout=timeout, proxy=proxy) as client:
                response = await client.head(self.CHECK_URL)
                
            response_time = time.time() - start_time
            
            # Check response status
            is_available = response.status_code in [200, 204, 301, 302, 307, 308]
            
            result = ProxyCheckResult(
                proxy=proxy,
                is_available=is_available,
                response_time=round(response_time, 3),
                error_message=None if is_available else f"HTTP {response.status_code}",
                checked_at=time.time()
            )
            
            logger.info(f"Proxy check completed: {proxy}, available: {is_available}, response_time: {response_time:.3f}s")
            
        except asyncio.TimeoutError:
            result = ProxyCheckResult(
                proxy=proxy,
                is_available=False,
                error_message="Connection timeout",
                checked_at=time.time()
            )
            logger.warning(f"Proxy check timeout: {proxy}")
            
        except Exception as e:
            result = ProxyCheckResult(
                proxy=proxy,
                is_available=False,
                error_message=str(e),
                checked_at=time.time()
            )
            logger.error(f"Proxy check failed: {proxy}, error: {str(e)}")
        
        # Cache result
        self._cache_result(result)
        return result
    
    async def check_multiple_proxies(
        self, 
        proxies: List[str], 
        use_cache: bool = True,
        max_concurrent: int = 5
    ) -> List[ProxyCheckResult]:
        """
        Check multiple proxies concurrently
        
        Args:
            proxies: List of proxy addresses
            use_cache: Whether to use cached results
            max_concurrent: Maximum concurrent check count
            
        Returns:
            List[ProxyCheckResult]: List of check results
        """
        if not proxies:
            return []
        
        logger.info(f"Starting batch proxy check for {len(proxies)} proxies")
        
        # Use semaphore to limit concurrency
        semaphore = asyncio.Semaphore(max_concurrent)
        
        async def check_with_semaphore(proxy: str) -> ProxyCheckResult:
            async with semaphore:
                return await self.check_single_proxy(proxy, use_cache)
        
        # Execute checks concurrently
        tasks = [check_with_semaphore(proxy) for proxy in proxies]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Handle exception results
        final_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"Proxy check task exception: {proxies[i]}, error: {str(result)}")
                final_results.append(ProxyCheckResult(
                    proxy=proxies[i],
                    is_available=False,
                    error_message=f"Check task exception: {str(result)}",
                    checked_at=time.time()
                ))
            else:
                final_results.append(result)
        
        available_count = sum(1 for r in final_results if r.is_available)
        logger.info(f"Batch proxy check completed: {available_count}/{len(proxies)} proxies available")
        
        return final_results
    
    def get_cache_stats(self) -> Dict[str, int]:
        """Get cache statistics"""
        current_time = time.time()
        valid_cache_count = sum(
            1 for result in self._cache.values()
            if current_time - result.checked_at < self.CACHE_DURATION
        )
        
        return {
            "total_cached": len(self._cache),
            "valid_cached": valid_cache_count,
            "expired_cached": len(self._cache) - valid_cache_count
        }
    
    def clear_cache(self) -> None:
        """Clear all cache"""
        self._cache.clear()
        logger.info("Proxy check cache cleared")


# Global instance
_proxy_check_service: Optional[ProxyCheckService] = None


def get_proxy_check_service() -> ProxyCheckService:
    """Get proxy check service instance"""
    global _proxy_check_service
    if _proxy_check_service is None:
        _proxy_check_service = ProxyCheckService()
    return _proxy_check_service 