# Job execution contract

The total deadline includes all attempts and waits. Before each attempt, timeout must not exceed
remaining total time. Service callbacks honor the timeout they receive; callers supply positive
timeouts and nonnegative waits. A wait stops at the deadline and cannot overshoot it.
No call starts at or after the deadline. max_attempts counts all started calls, including the first.
429 and 5xx can retry; other 4xx stop. Completion is accepted if the service succeeds within its timeout.
The public result includes status, attempts and elapsed. VirtualClock avoids real sleeps.
The independent backoff preview displays its full exponential sequence and is not deadline-capped.
