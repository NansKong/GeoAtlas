class ProviderScorer:
    """
    Evaluates APIs dynamically and routes around total backend failures iteratively. 
    Maintains a pass/fail matrix to isolate unstable providers from killing batches.
    """
    def __init__(self, failure_threshold=0.6):
        self.scores = {}
        self.failure_threshold = failure_threshold

    def _init_provider(self, provider: str):
        if provider not in self.scores:
            self.scores[provider] = {"success": 0.0, "fail": 0.0, "skip": 0.0}

    def record_success(self, provider: str):
        self._init_provider(provider)
        self.scores[provider]["success"] += 1.0

    def record_fail(self, provider: str, weight=1.0):
        self._init_provider(provider)
        self.scores[provider]["fail"] += weight

    def record_skip(self, provider: str):
        self._init_provider(provider)
        self.scores[provider]["skip"] += 1.0

    def get_score(self, provider: str):
        stats = self.scores.get(provider, {"success": 0.0, "fail": 0.0, "skip": 0.0})
        
        # Skip count explicitly decoupled from failure denominator (resource decisions aren't crashes)
        total_attempts = stats["success"] + stats["fail"]
        
        # Default to 1.0 (perfect) if we have no footprint
        if total_attempts == 0.0:
            return 1.0
            
        return stats["success"] / total_attempts

    def should_fallback(self, provider: str, min_attempts=3):
        """
        Calculates if the provider is statistically unstable to justify cutting connection dynamically.
        Requires a minimum number of attempts to avoid false positives.
        """
        stats = self.scores.get(provider, {"success": 0.0, "fail": 0.0})
        total_attempts = stats["success"] + stats["fail"]
        
        if total_attempts < min_attempts:
            return False # Let it keep trying
            
        if stats["success"] < 2.0:
            return False # Prevent early panic if the provider hasn't even established a footprint
            
        return self.get_score(provider) < self.failure_threshold
