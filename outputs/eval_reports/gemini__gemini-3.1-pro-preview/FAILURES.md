# Worst 15 predictions — gemini__gemini-3.1-pro-preview

_Sorted by cell accuracy (within 5%). 300 scored total._


## 1. `0004253` — cell acc 0%  (type=stacked_bar, labels_shown=True, augmented=True)

![0004253](../../../data/synthetic_v0/images/0004253.png)

**Ground truth:**
```csv
Region,Product C,Product A,Product B,Product E
East,75347.0,45899.0,61650.0,87298.0
APAC,67314.0,66727.0,24471.0,90503.0
North,1404.0,38840.0,93192.0,35531.0
EMEA,7053.0,77382.0,4168.0,13416.0
South,93173.0,45297.0,43610.0,50035.0
West,68825.0,91545.0,63505.0,62002.0
LATAM,55645.0,36982.0,5108.0,26489.0
Central,90761.0,4555.0,33116.0,93862.0
Region 9,76807.0,69480.0,30753.0,29645.0
Region 10,30363.0,89007.0,71385.0,69941.0
Region 11,63184.0,65119.0,57468.0,15955.0
```

**Prediction:** unparseable — ClientError: 429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': 'You exceeded your current quota, please check your plan and billing details. For more information on this error, head to: https://ai.google.dev/gemini-api/docs/rate-limits. To monitor your current usage, head to: https://ai.dev/rate-limit. \n* Quota exceeded for metric: generativelanguage.googleapis.com/generate_requests_per_model_per_day, limit: 250, model: gemini-3.1-pro\nPlease retry in 17m49.529651452s.', 'status': 'RESOURCE_EXHAUSTED', 'details': [{'@type': 'type.googleapis.com/google.rpc.Help', 'links': [{'description': 'Learn more about Gemini API quotas', 'url': 'https://ai.google.dev/gemini-api/docs/rate-limits'}]}, {'@type': 'type.googleapis.com/google.rpc.QuotaFailure', 'violations': [{'quotaMetric': 'generativelanguage.googleapis.com/generate_requests_per_model_per_day', 'quotaId': 'GenerateRequestsPerDayPerProjectPerModel', 'quotaDimensions': {'location': 'global', 'model': 'gemini-3.1-pro'}, 'quotaValue': '250'}]}, {'@type': 'type.googleapis.com/google.rpc.RetryInfo', 'retryDelay': '1069s'}]}}
```
(empty)
```

## 2. `0003335` — cell acc 0%  (type=multi_line, labels_shown=False, augmented=True)

![0003335](../../../data/synthetic_v0/images/0003335.png)

**Ground truth:**
```csv
Year,Product D,Product C,Product E,Product F
2001,1.0,0.0,0.0,1.0
2002,0.0,1.0,1.0,1.0
2003,1.0,0.0,0.0,1.0
2004,0.0,0.0,1.0,1.0
2005,1.0,0.0,0.0,1.0
2006,1.0,0.0,0.0,1.0
2007,0.0,0.0,1.0,0.0
2008,1.0,1.0,1.0,0.0
2009,0.0,0.0,0.0,1.0
2010,0.0,1.0,0.0,1.0
2011,0.0,0.0,1.0,0.0
```

**Prediction:** unparseable — ClientError: 429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': 'You exceeded your current quota, please check your plan and billing details. For more information on this error, head to: https://ai.google.dev/gemini-api/docs/rate-limits. To monitor your current usage, head to: https://ai.dev/rate-limit. \n* Quota exceeded for metric: generativelanguage.googleapis.com/generate_requests_per_model_per_day, limit: 250, model: gemini-3.1-pro\nPlease retry in 4m2.161624479s.', 'status': 'RESOURCE_EXHAUSTED', 'details': [{'@type': 'type.googleapis.com/google.rpc.Help', 'links': [{'description': 'Learn more about Gemini API quotas', 'url': 'https://ai.google.dev/gemini-api/docs/rate-limits'}]}, {'@type': 'type.googleapis.com/google.rpc.QuotaFailure', 'violations': [{'quotaMetric': 'generativelanguage.googleapis.com/generate_requests_per_model_per_day', 'quotaId': 'GenerateRequestsPerDayPerProjectPerModel', 'quotaDimensions': {'location': 'global', 'model': 'gemini-3.1-pro'}, 'quotaValue': '250'}]}, {'@type': 'type.googleapis.com/google.rpc.RetryInfo', 'retryDelay': '242s'}]}}
```
(empty)
```

## 3. `0000577` — cell acc 0%  (type=stacked_bar, labels_shown=True, augmented=True)

![0000577](../../../data/synthetic_v0/images/0000577.png)

**Ground truth:**
```csv
Month,Product E,Product B,Product A,Product C
Jan,715.0,368.0,100.0,72.0
Feb,36.0,617.0,406.0,94.0
Mar,707.0,340.0,855.0,899.0
Apr,70.0,955.0,504.0,331.0
May,177.0,380.0,145.0,920.0
Jun,416.0,185.0,193.0,740.0
Jul,189.0,88.0,41.0,909.0
Aug,93.0,283.0,875.0,151.0
Sep,592.0,653.0,104.0,483.0
Oct,20.0,70.0,458.0,313.0
Nov,581.0,85.0,816.0,240.0
```

**Prediction:** unparseable — ConnectError: [Errno 8] nodename nor servname provided, or not known
```
(empty)
```

## 4. `0002452` — cell acc 0%  (type=grouped_bar, labels_shown=True, augmented=True)

![0002452](../../../data/synthetic_v0/images/0002452.png)

**Ground truth:**
```csv
Year,Series 1,Series 2,Series 3,Series 4
2010,109.4,649.6,836.1,306.7
2011,450.0,230.3,702.9,500.8
2012,884.0,968.8,34.3,711.0
2013,890.3,797.2,946.3,44.0
2014,547.4,15.0,964.2,600.6
2015,380.3,708.9,855.4,384.3
2016,418.3,640.6,784.6,175.5
2017,954.5,969.3,784.3,914.6
2018,484.7,379.0,283.9,224.8
2019,900.6,658.2,724.2,936.5
2020,921.2,580.3,513.1,401.9
```

**Prediction:** unparseable — ConnectError: [Errno 8] nodename nor servname provided, or not known
```
(empty)
```

## 5. `0004732` — cell acc 0%  (type=stacked_bar, labels_shown=False, augmented=False)

![0004732](../../../data/synthetic_v0/images/0004732.png)

**Ground truth:**
```csv
Product,North,Central,APAC,EMEA
Product A,66877.15,37682.02,91375.4,31262.58
Product E,47537.46,56283.32,87437.72,36268.02
Product D,4061.34,21644.9,88963.83,70620.41
Product C,82171.81,74442.15,5382.43,35003.3
Product B,76797.44,10105.61,85257.01,73732.24
Product F,62456.26,88478.25,58525.09,71262.93
Product G,35512.81,32501.12,34198.86,20772.52
Product H,49812.87,79575.04,71182.28,16861.79
Product I,84718.66,95191.76,15836.41,13669.93
Product J,23387.95,3951.46,34773.84,6698.36
```

**Prediction:** unparseable — ConnectError: [Errno 8] nodename nor servname provided, or not known
```
(empty)
```

## 6. `0001736` — cell acc 0%  (type=multi_line, labels_shown=True, augmented=True)

![0001736](../../../data/synthetic_v0/images/0001736.png)

**Ground truth:**
```csv
Category,Series 1,Series 2,Series 3,Series 4
Cat 1,4.5,1.3,2.7,0.9
Cat 2,1.3,8.8,5.9,5.2
Cat 3,2.5,6.2,3.2,0.2
Cat 4,8.8,2.4,8.0,5.5
Cat 5,3.3,8.9,3.0,1.3
Cat 6,0.4,0.1,7.6,9.9
Cat 7,2.0,0.5,5.2,5.7
Cat 8,0.5,4.7,6.0,1.2
Cat 9,7.5,6.7,1.3,2.4
```

**Prediction:** unparseable — ClientError: 429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': 'You exceeded your current quota, please check your plan and billing details. For more information on this error, head to: https://ai.google.dev/gemini-api/docs/rate-limits. To monitor your current usage, head to: https://ai.dev/rate-limit. \n* Quota exceeded for metric: generativelanguage.googleapis.com/generate_requests_per_model_per_day, limit: 250, model: gemini-3.1-pro\nPlease retry in 23h57m10.781588465s.', 'status': 'RESOURCE_EXHAUSTED', 'details': [{'@type': 'type.googleapis.com/google.rpc.Help', 'links': [{'description': 'Learn more about Gemini API quotas', 'url': 'https://ai.google.dev/gemini-api/docs/rate-limits'}]}, {'@type': 'type.googleapis.com/google.rpc.QuotaFailure', 'violations': [{'quotaMetric': 'generativelanguage.googleapis.com/generate_requests_per_model_per_day', 'quotaId': 'GenerateRequestsPerDayPerProjectPerModel', 'quotaDimensions': {'location': 'global', 'model': 'gemini-3.1-pro'}, 'quotaValue': '250'}]}, {'@type': 'type.googleapis.com/google.rpc.RetryInfo', 'retryDelay': '86230s'}]}}
```
(empty)
```

## 7. `0001904` — cell acc 0%  (type=multi_line, labels_shown=False, augmented=True)

![0001904](../../../data/synthetic_v0/images/0001904.png)

**Ground truth:**
```csv
Category,Series 1,Series 2,Series 3,Series 4
Cat 1,259926.0,236535.0,123788.0,280613.0
Cat 2,886956.0,807999.0,86737.0,704730.0
Cat 3,270333.0,674732.0,111309.0,989694.0
Cat 4,861806.0,550325.0,472292.0,246602.0
Cat 5,278292.0,255025.0,526589.0,630227.0
Cat 6,833986.0,385954.0,689076.0,443330.0
Cat 7,933274.0,503037.0,476069.0,849267.0
Cat 8,193657.0,809238.0,200232.0,560333.0
Cat 9,958035.0,232908.0,825205.0,577678.0
```

**Prediction:** unparseable — ConnectError: [Errno 8] nodename nor servname provided, or not known
```
(empty)
```

## 8. `0004466` — cell acc 0%  (type=grouped_bar, labels_shown=False, augmented=False)

![0004466](../../../data/synthetic_v0/images/0004466.png)

**Ground truth:**
```csv
x,Series 1,Series 2,Series 3
Jan,8.0,6.0,3.0
Feb,1.0,8.0,10.0
Mar,8.0,5.0,1.0
Apr,3.0,10.0,1.0
May,4.0,1.0,4.0
Jun,7.0,9.0,0.0
Jul,1.0,2.0,3.0
Aug,1.0,5.0,4.0
Sep,4.0,3.0,10.0
Oct,4.0,1.0,3.0
Nov,8.0,1.0,2.0
Dec,2.0,9.0,7.0
```

**Prediction:** unparseable — ConnectError: [Errno 8] nodename nor servname provided, or not known
```
(empty)
```

## 9. `0003840` — cell acc 0%  (type=multi_line, labels_shown=False, augmented=True)

![0003840](../../../data/synthetic_v0/images/0003840.png)

**Ground truth:**
```csv
Category,North,APAC,Central
Cat 1,0.6,0.8,0.2
Cat 2,0.5,0.1,0.1
Cat 3,0.1,1.0,0.9
Cat 4,0.1,0.5,0.2
Cat 5,0.1,0.7,0.0
Cat 6,0.1,0.8,0.1
Cat 7,0.3,0.5,0.9
Cat 8,0.4,0.8,0.5
Cat 9,0.6,0.2,0.8
Cat 10,0.4,0.9,1.0
Cat 11,1.0,0.1,0.2
```

**Prediction:** unparseable — ConnectError: [Errno 8] nodename nor servname provided, or not known
```
(empty)
```

## 10. `0003844` — cell acc 0%  (type=grouped_bar, labels_shown=True, augmented=True)

![0003844](../../../data/synthetic_v0/images/0003844.png)

**Ground truth:**
```csv
Quarter,LATAM,Central,APAC,South
Q1 2016,98493.5,44353.5,22825.5,18455.5
Q2 2016,21660.1,40635.9,72100.3,74269.3
Q3 2016,17899.3,24318.2,16169.9,2117.7
Q4 2016,18540.5,1883.3,71421.6,94937.4
Q1 2017,62363.3,52830.2,77174.6,82145.5
Q2 2017,77777.7,36439.4,41910.4,89712.2
Q3 2017,57251.5,21465.9,5774.8,48945.1
Q4 2017,15422.2,86636.6,29546.8,98177.6
```

**Prediction:** unparseable — ClientError: 429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': 'You exceeded your current quota, please check your plan and billing details. For more information on this error, head to: https://ai.google.dev/gemini-api/docs/rate-limits. To monitor your current usage, head to: https://ai.dev/rate-limit. \n* Quota exceeded for metric: generativelanguage.googleapis.com/generate_requests_per_model_per_day, limit: 250, model: gemini-3.1-pro\nPlease retry in 23h59m28.560832801s.', 'status': 'RESOURCE_EXHAUSTED', 'details': [{'@type': 'type.googleapis.com/google.rpc.Help', 'links': [{'description': 'Learn more about Gemini API quotas', 'url': 'https://ai.google.dev/gemini-api/docs/rate-limits'}]}, {'@type': 'type.googleapis.com/google.rpc.QuotaFailure', 'violations': [{'quotaMetric': 'generativelanguage.googleapis.com/generate_requests_per_model_per_day', 'quotaId': 'GenerateRequestsPerDayPerProjectPerModel', 'quotaDimensions': {'location': 'global', 'model': 'gemini-3.1-pro'}, 'quotaValue': '250'}]}, {'@type': 'type.googleapis.com/google.rpc.RetryInfo', 'retryDelay': '86368s'}]}}
```
(empty)
```

## 11. `0003747` — cell acc 0%  (type=multi_line, labels_shown=False, augmented=True)

![0003747](../../../data/synthetic_v0/images/0003747.png)

**Ground truth:**
```csv
Year,LATAM,EMEA,South,East
2007,5187.0,1282.0,3675.0,355.0
2008,8041.0,8273.0,363.0,3481.0
2009,757.0,3512.0,8338.0,5495.0
2010,4994.0,2958.0,5350.0,2762.0
2011,6950.0,4658.0,1461.0,9157.0
2012,9092.0,4773.0,6711.0,1901.0
2013,363.0,8283.0,4219.0,8724.0
2014,6693.0,5395.0,9136.0,8571.0
```

**Prediction:** unparseable — ConnectError: [Errno 8] nodename nor servname provided, or not known
```
(empty)
```

## 12. `0003422` — cell acc 0%  (type=grouped_bar, labels_shown=False, augmented=True)

![0003422](../../../data/synthetic_v0/images/0003422.png)

**Ground truth:**
```csv
Region,Central,South,East
North,17149.5,97558.6,86289.5
LATAM,83632.9,96711.5,41245.2
APAC,95214.6,70707.7,45.6
EMEA,42548.3,15570.8,37566.0
South,24104.2,67801.1,12859.4
West,99324.2,45385.4,85512.7
East,23384.5,12544.2,36056.4
Central,27635.0,4738.8,39550.1
Region 9,50114.9,44603.8,93025.3
Region 10,45425.8,40304.2,75616.3
```

**Prediction:** unparseable — ConnectError: [Errno 8] nodename nor servname provided, or not known
```
(empty)
```

## 13. `0002220` — cell acc 0%  (type=stacked_bar, labels_shown=True, augmented=True)

![0002220](../../../data/synthetic_v0/images/0002220.png)

**Ground truth:**
```csv
Quarter,Series 1,Series 2,Series 3
Q1 2019,82671.0,73122.0,37119.0
Q2 2019,28495.0,72639.0,77551.0
Q3 2019,29852.0,41760.0,5056.0
Q4 2019,18648.0,5536.0,5338.0
Q1 2020,84208.0,60842.0,68004.0
Q2 2020,75169.0,9912.0,92058.0
Q3 2020,55131.0,58136.0,58423.0
Q4 2020,43648.0,67192.0,97994.0
Q1 2021,58219.0,87454.0,71716.0
```

**Prediction:** unparseable — ConnectError: [Errno 8] nodename nor servname provided, or not known
```
(empty)
```

## 14. `0002239` — cell acc 0%  (type=multi_line, labels_shown=False, augmented=True)

![0002239](../../../data/synthetic_v0/images/0002239.png)

**Ground truth:**
```csv
Year,Product A,Product D,Product B
2004,61226.0,98908.0,79844.0
2005,64819.0,56050.0,1660.0
2006,24533.0,70231.0,48619.0
2007,24578.0,69645.0,51381.0
2008,47983.0,73089.0,77087.0
2009,4514.0,43268.0,5097.0
```

**Prediction:** unparseable — ClientError: 429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': 'You exceeded your current quota, please check your plan and billing details. For more information on this error, head to: https://ai.google.dev/gemini-api/docs/rate-limits. To monitor your current usage, head to: https://ai.dev/rate-limit. \n* Quota exceeded for metric: generativelanguage.googleapis.com/generate_requests_per_model_per_day, limit: 250, model: gemini-3.1-pro\nPlease retry in 10m56.226430958s.', 'status': 'RESOURCE_EXHAUSTED', 'details': [{'@type': 'type.googleapis.com/google.rpc.Help', 'links': [{'description': 'Learn more about Gemini API quotas', 'url': 'https://ai.google.dev/gemini-api/docs/rate-limits'}]}, {'@type': 'type.googleapis.com/google.rpc.QuotaFailure', 'violations': [{'quotaMetric': 'generativelanguage.googleapis.com/generate_requests_per_model_per_day', 'quotaId': 'GenerateRequestsPerDayPerProjectPerModel', 'quotaDimensions': {'location': 'global', 'model': 'gemini-3.1-pro'}, 'quotaValue': '250'}]}, {'@type': 'type.googleapis.com/google.rpc.RetryInfo', 'retryDelay': '656s'}]}}
```
(empty)
```

## 15. `0002927` — cell acc 0%  (type=multi_line, labels_shown=False, augmented=True)

![0002927](../../../data/synthetic_v0/images/0002927.png)

**Ground truth:**
```csv
Product,Product F,Product D
Product C,77.0,82.0
Product A,51.0,18.0
Product E,67.0,14.0
Product F,2.0,26.0
Product D,45.0,15.0
Product B,25.0,11.0
Product G,53.0,52.0
Product H,62.0,57.0
Product I,94.0,62.0
```

**Prediction:** unparseable — ConnectError: [Errno 8] nodename nor servname provided, or not known
```
(empty)
```
