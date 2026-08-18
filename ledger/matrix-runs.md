# Matrix runs

Append-only. Each entry is one `smoke.py --matrix` sweep: every registry model against every attachment kind and the two-call cache demo. Cache values are OBSERVED, never asserted.

## 2026-08-18 17:47:16Z

```
model                                image  pdf                text         cache c1     cache c2     cost    
--------------------------------------------------------------------------------------------------------------
anthropic/claude-opus-5              OK     UNAVAILABLE        UNAVAILABLE  UNAVAILABLE  UNAVAILABLE  0.011555
anthropic/claude-sonnet-5            OK     OK                 OK           0/6544       6544/0       0.023419
openai/gpt-5.6-sol                   OK     OK                 OK           0/0          3674/0       0.030840
anthropic/claude-fable-5             OK     OK                 OK           0/6544       6544/0       0.116944
anthropic/claude-haiku-4-5-20251001  OK     OK                 OK           0/4142       4142/0       0.007789
openai/gpt-5.6-luna                  OK     OK                 OK           0/0          3674/0       0.001164
openai/gpt-5.6-terra                 OK     OK                 OK           0/0          3674/0       0.012614
gemini/gemini-3.7-flash              OK     OK                 OK           0/0          4072/0       0.010571
xai/grok-4.6                         OK     REFUSED-by-design  OK           128/0        3840/0       0.025824

9 models swept. Total cost: $0.240719
```
