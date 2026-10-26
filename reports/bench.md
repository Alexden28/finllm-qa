Checker on AMD Ryzen 9 8940HX with Radeon Graphics (one core, pure Python):

| Texts | Count | Median | 95th percentile | Throughput |
| --- | --- | --- | --- | --- |
| LLM commentaries | 1,068 | 2.0 ms | 4.2 ms | 464 texts/s |
| benchmark documents | 3,739 | 1.1 ms | 2.2 ms | 843 texts/s |

Generation on NVIDIA GeForce RTX 5070 Laptop GPU (bf16, greedy, batch 8, up to 180 new tokens, 32 briefs):

| Model | Parameters | Seconds per commentary | Tokens/s, batch of 8 | Peak GPU memory | Load time |
| --- | --- | --- | --- | --- | --- |
| Qwen2.5-0.5B-Instruct | 494M | 0.73 | 150 | 1.0 GB | 2 s |
| Qwen2.5-1.5B-Instruct | 1,544M | 1.00 | 129 | 3.0 GB | 3 s |
| SmolLM2-1.7B-Instruct | 1,711M | 0.58 | 167 | 3.7 GB | 2 s |
| granite-3.3-2b-instruct | 2,534M | 1.24 | 118 | 5.0 GB | 4 s |
