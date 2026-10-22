# Distance analysis: qa_all_five_live2017

Geocoded buildings 9,832 / 10,025; transactions with spatial coverage 974,040 / 989,492.

## Nearest-centre distance (m)

| Distribution | p0 | p10 | p25 | p50 | p75 | p90 | p95 | p99 | p100 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| nearest hawker, by buildings | 8 | 235 | 478 | 1,442 | 2,754 | 4,494 | 5,317 | 5,933 | 7,085 |
| nearest hawker, by transactions | 8 | 210 | 373 | 987 | 2,202 | 3,960 | 4,870 | 5,730 | 7,085 |
| nearest fresh-market, by buildings | 11 | 246 | 488 | 1,444 | 2,755 | 4,494 | 5,317 | 5,933 | 7,085 |
| nearest fresh-market, by transactions | 11 | 218 | 382 | 990 | 2,203 | 3,960 | 4,870 | 5,730 | 7,085 |

## Classes under the contract (near < 500 m, medium < 1000 m, far >= 1000 m)

| Query basis | near (buildings / transactions) | medium (buildings / transactions) | far (buildings / transactions) |
|---|---|---|---|
| Q4 nearest hawker | 2,543 / 327,823 | 1,467 / 162,314 | 5,822 / 483,903 |
| Q5 nearest fresh-market | 2,505 / 323,449 | 1,498 / 166,136 | 5,829 / 484,455 |

Q4 town x flat_type cells with both near and far sales: 53 of 131.

## Threshold sensitivity (transactions)

| near < | far >= | Q4 near / medium / far | Q5 near / medium / far | Q4 cells with near and far |
|---:|---:|---|---|---:|
| 300 | 800 | 176,344 / 258,708 / 538,988 | 170,997 / 261,712 / 541,331 | 56 of 131 |
| 400 | 800 | 266,453 / 168,599 / 538,988 | 260,954 / 171,755 / 541,331 | 59 of 131 |
| 500 | 1000 | 327,823 / 162,314 / 483,903 | 323,449 / 166,136 / 484,455 | 53 of 131 |
| 500 | 1500 | 327,823 / 268,358 / 377,859 | 323,449 / 272,088 / 378,503 | 29 of 131 |
| 750 | 1500 | 420,703 / 175,478 / 377,859 | 418,204 / 177,333 / 378,503 | 34 of 131 |

## F-03: sales beyond a maximum effective distance

| Cap (m) | Q5 buildings / transactions beyond | Q4 buildings / transactions beyond |
|---:|---|---|
| 1000 | 5,829 / 484,455 | 5,822 / 483,903 |
| 1500 | 4,796 / 378,503 | 4,788 / 377,859 |
| 2000 | 3,693 / 281,099 | 3,688 / 280,795 |
| 2500 | 2,780 / 200,489 | 2,778 / 200,388 |
| 3000 | 2,214 / 154,732 | 2,207 / 154,216 |

Rule from F-03 (smallest 250 m step >= p95, max 2000): p95 = 5,317 m -> 2000 m.

## F-02: geo-only centres (not in the NEA inventory)

25 geo-only centres are closer than the nearest NEA centre for 5,769 buildings (486,363 transactions).

| Q4 class change if they were included | Transactions |
|---|---:|
| far->medium (2017+) | 56,171 |
| far->medium (before 2017) | 125,631 |
| far->near (2017+) | 30,004 |
| far->near (before 2017) | 56,576 |
| medium->near (2017+) | 1,472 |
| medium->near (before 2017) | 5,785 |
