class VirtualClock:
    def __init__(self):
        self.elapsed = 0.0

    def now(self):
        return self.elapsed

    def advance(self, seconds):
        self.elapsed += seconds
