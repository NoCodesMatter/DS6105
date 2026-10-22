# Distance analysis: stage1_2015_2016

Geocoded buildings 7,903 / 7,921; transactions with spatial coverage 37,057 / 37,153.

## Nearest-centre distance (m)

| Distribution | p0 | p10 | p25 | p50 | p75 | p90 | p95 | p99 | p100 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| nearest hawker, by buildings | 8 | 226 | 436 | 1,303 | 2,566 | 4,271 | 5,119 | 5,672 | 6,129 |
| nearest hawker, by transactions | 8 | 221 | 393 | 1,246 | 2,685 | 4,429 | 5,258 | 5,638 | 6,129 |
| nearest fresh-market, by buildings | 11 | 235 | 443 | 1,308 | 2,568 | 4,271 | 5,119 | 5,672 | 6,129 |
| nearest fresh-market, by transactions | 11 | 228 | 398 | 1,254 | 2,685 | 4,429 | 5,258 | 5,638 | 6,129 |

## Classes under the contract (near < 500 m, medium < 1000 m, far >= 1000 m)

| Query basis | near (buildings / transactions) | medium (buildings / transactions) | far (buildings / transactions) |
|---|---|---|---|
| Q4 nearest hawker | 2,222 / 11,689 | 1,235 / 5,288 | 4,446 / 20,080 |
| Q5 nearest fresh-market | 2,193 / 11,546 | 1,258 / 5,409 | 4,452 / 20,102 |

Q4 town x flat_type cells with both near and far sales: 45 of 124.

## Threshold sensitivity (transactions)

| near < | far >= | Q4 near / medium / far | Q5 near / medium / far | Q4 cells with near and far |
|---:|---:|---|---|---:|
| 300 | 800 | 6,331 / 8,770 / 21,956 | 6,176 / 8,844 / 22,037 | 47 of 124 |
| 400 | 800 | 9,486 / 5,615 / 21,956 | 9,306 / 5,714 / 22,037 | 52 of 124 |
| 500 | 1000 | 11,689 / 5,288 / 20,080 | 11,546 / 5,409 / 20,102 | 45 of 124 |
| 500 | 1500 | 11,689 / 8,835 / 16,533 | 11,546 / 8,955 / 16,556 | 23 of 124 |
| 750 | 1500 | 14,600 / 5,924 / 16,533 | 14,527 / 5,974 / 16,556 | 28 of 124 |

## F-03: sales beyond a maximum effective distance

| Cap (m) | Q5 buildings / transactions beyond | Q4 buildings / transactions beyond |
|---:|---|---|
| 1000 | 4,452 / 20,102 | 4,446 / 20,080 |
| 1500 | 3,573 / 16,556 | 3,566 / 16,533 |
| 2000 | 2,737 / 13,255 | 2,732 / 13,238 |
| 2500 | 2,038 / 10,186 | 2,036 / 10,176 |
| 3000 | 1,613 / 7,987 | 1,609 / 7,947 |

Rule from F-03 (smallest 250 m step >= p95, max 2000): p95 = 5,119 m -> 2000 m.

## F-02: geo-only centres (not in the NEA inventory)

25 geo-only centres are closer than the nearest NEA centre for 4,350 buildings (19,926 transactions).

| Q4 class change if they were included | Transactions |
|---|---:|
| far->medium (before 2017) | 7,578 |
| far->near (before 2017) | 4,025 |
| medium->near (before 2017) | 197 |
