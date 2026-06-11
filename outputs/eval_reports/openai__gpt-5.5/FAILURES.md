# Worst 15 predictions — openai__gpt-5.5

_Sorted by cell accuracy (within 5%). 300 scored total._


## 1. `0003906` — cell acc 0%  (type=stacked_bar, labels_shown=False, augmented=True)

![0003906](../../../data/synthetic_v0/images/0003906.png)

**Ground truth:**
```csv
Year,Product F,Product A,Product C,Product B
2014,166578.38,249047.14,348641.77,674560.88
2015,148776.99,163869.89,473166.45,680992.25
2016,877986.9,431696.38,965577.35,153175.73
2017,556489.0,737420.36,556202.93,48440.44
```

**Prediction:**
```csv
Year,Product A,Product B,Product C,Product D
2014,0.17,0.23,0.36,0.66
2015,0.15,0.16,0.44,0.68
2016,0.86,0.43,0.95,0.13
2017,0.54,0.74,0.54,0.05
```

## 2. `0004641` — cell acc 0%  (type=stacked_bar, labels_shown=True, augmented=True)

![0004641](../../../data/synthetic_v0/images/0004641.png)

**Ground truth:**
```csv
Quarter,Series 1,Series 2
Q2 2017,277684.2,595357.6
Q3 2017,536843.4,273182.4
Q4 2017,846328.3,614966.7
Q1 2018,629879.0,793313.1
Q2 2018,690758.5,52866.6
Q3 2018,147418.6,924139.7
Q4 2018,631284.4,80824.7
```

**Prediction:** unparseable — RateLimitError: Error code: 429 - {'error': {'message': 'You exceeded your current quota, please check your plan and billing details. For more information on this error, read the docs: https://platform.openai.com/docs/guides/error-codes/api-errors.', 'type': 'insufficient_quota', 'param': None, 'code': 'insufficient_quota'}}
```
(empty)
```

## 3. `0002512` — cell acc 0%  (type=multi_line, labels_shown=True, augmented=True)

![0002512](../../../data/synthetic_v0/images/0002512.png)

**Ground truth:**
```csv
Product,South,EMEA,East,West
Product F,672.0,401.0,371.0,971.0
Product A,320.0,704.0,978.0,600.0
Product D,506.0,750.0,323.0,755.0
```

**Prediction:**
```csv
Month,series_1,series_2,series_3
January,60.0,30.0,10.0
February,30.0,0.0,60.0
March,40.0,20.0,0.0
```

## 4. `0004815` — cell acc 0%  (type=bar, labels_shown=False, augmented=True)

![0004815](../../../data/synthetic_v0/images/0004815.png)

**Ground truth:**
```csv
Year,Population
2012,39.0
2013,-205.0
2014,535.0
2015,144.0
2016,821.0
2017,176.0
2018,403.0
2019,588.0
2020,878.0
2021,544.0
2022,-419.0
```

**Prediction:**
```csv
x,Population
2012,30.0
2013,-220.0
2014,500.0
2015,100.0
2016,760.0
2017,120.0
2018,350.0
2019,550.0
2020,800.0
2021,450.0
2022,-500.0
```

## 5. `0002296` — cell acc 0%  (type=pie, labels_shown=False, augmented=False)

![0002296](../../../data/synthetic_v0/images/0002296.png)

**Ground truth:**
```csv
category,value
Cat 1,48677.74
Cat 2,15661.76
Cat 3,61528.24
Cat 4,16885.55
Cat 5,7743.03
Cat 6,71402.62
Cat 7,94830.31
```

**Prediction:** unparseable — schema[0]: 14 error(s)
```
{"chart_type":"pie","title":"Category GDP","x_axis":{"label":null,"unit":null},"y_axis":{"label":null,"unit":null},"series":[{"name":"GDP","points":[{"category":"Cat 1","value":15},{"category":"Cat 2","value":5},{"category":"Cat 3","value":20},{"category":"Cat 4","value":5},{"category":"Cat 5","value":3},{"category":"Cat 6","value":22},{"category":"Cat 7","value":30}]}]}
```

## 6. `0002732` — cell acc 0%  (type=pie, labels_shown=True, augmented=True)

![0002732](../../../data/synthetic_v0/images/0002732.png)

**Ground truth:**
```csv
category,value
LATAM,1876.0
EMEA,85068.0
East,17931.0
West,15954.0
APAC,40888.0
South,42200.0
North,11946.0
```

**Prediction:** unparseable — schema[0]: 14 error(s)
```
{"chart_type":"pie","title":"Sales by Region","x_axis":{"label":null,"unit":null},"y_axis":{"label":null,"unit":null},"series":[{"name":null,"points":[{"category":"EMEA","value":85068},{"category":"LATAM","value":1876},{"category":"North","value":11946},{"category":"South","value":42200},{"category":"APAC","value":40888},{"category":"West","value":15954},{"category":"East","value":17931}]}]}
```

## 7. `0004911` — cell acc 0%  (type=pie, labels_shown=True, augmented=True)

![0004911](../../../data/synthetic_v0/images/0004911.png)

**Ground truth:**
```csv
category,value
Cat 1,1307.0
Cat 2,2137.0
Cat 3,5095.0
Cat 4,6069.0
Cat 5,7135.0
Cat 6,6802.0
Cat 7,8853.0
```

**Prediction:** unparseable — schema[0]: 14 error(s)
```
{"chart_type":"pie","title":"Temperature per Category","x_axis":{"label":null,"unit":null},"y_axis":{"label":null,"unit":null},"series":[{"name":null,"points":[{"category":"Cat 1","value":1307},{"category":"Cat 2","value":2137},{"category":"Cat 3","value":5095},{"category":"Cat 4","value":6069},{"category":"Cat 5","value":7135},{"category":"Cat 6","value":6802},{"category":"Cat 7","value":8853}]}]}
```

## 8. `0000849` — cell acc 0%  (type=pie, labels_shown=False, augmented=True)

![0000849](../../../data/synthetic_v0/images/0000849.png)

**Ground truth:**
```csv
category,value
Mar,26042.0
Apr,68895.0
May,32680.0
Jun,77114.0
Jul,77378.0
Aug,66611.0
Sep,3780.0
```

**Prediction:** unparseable — schema[0]: 14 error(s)
```
{"chart_type":"pie","title":null,"x_axis":{"label":null,"unit":null},"y_axis":{"label":null,"unit":null},"series":[{"name":null,"points":[{"category":"Apr","value":20},{"category":"Mar","value":7},{"category":"Sep","value":1},{"category":"Aug","value":19},{"category":"Jul","value":22},{"category":"Jun","value":22},{"category":"May","value":9}]}]}
```

## 9. `0001709` — cell acc 0%  (type=pie, labels_shown=False, augmented=True)

![0001709](../../../data/synthetic_v0/images/0001709.png)

**Ground truth:**
```csv
category,value
Q1 2016,1459.0
Q2 2016,4902.0
Q3 2016,2747.0
Q4 2016,6133.0
Q1 2017,3316.0
Q2 2017,2551.0
Q3 2017,2976.0
```

**Prediction:** unparseable — schema[0]: 14 error(s)
```
{"chart_type":"pie","title":"Revenue Breakdown","x_axis":{"label":null,"unit":null},"y_axis":{"label":null,"unit":null},"series":[{"name":null,"points":[{"category":"Q1 2016","value":6},{"category":"Q2 2016","value":20},{"category":"Q3 2016","value":12},{"category":"Q4 2016","value":25},{"category":"Q1 2017","value":13},{"category":"Q2 2017","value":12},{"category":"Q3 2017","value":12}]}]}
```

## 10. `0004311` — cell acc 0%  (type=pie, labels_shown=False, augmented=False)

![0004311](../../../data/synthetic_v0/images/0004311.png)

**Ground truth:**
```csv
category,value
Product D,1.0
Product E,1.0
Product C,1.0
Product F,1.0
Product A,1.0
Product B,1.0
```

**Prediction:** unparseable — schema[0]: 12 error(s)
```
{"chart_type":"pie","title":null,"x_axis":{"label":null,"unit":null},"y_axis":{"label":null,"unit":null},"series":[{"name":null,"points":[{"category":"Product A","value":16.67},{"category":"Product B","value":16.67},{"category":"Product C","value":16.67},{"category":"Product D","value":16.67},{"category":"Product E","value":16.67},{"category":"Product F","value":16.67}]}]}
```

## 11. `0000270` — cell acc 0%  (type=pie, labels_shown=True, augmented=True)

![0000270](../../../data/synthetic_v0/images/0000270.png)

**Ground truth:**
```csv
category,value
Cat 1,5.6
Cat 2,6.54
Cat 3,6.91
Cat 4,5.91
Cat 5,5.65
Cat 6,5.37
```

**Prediction:** unparseable — schema[0]: 12 error(s)
```
{"chart_type":"pie","title":"Throughput Overview","x_axis":{"label":null,"unit":null},"y_axis":{"label":null,"unit":null},"series":[{"name":null,"points":[{"category":"Cat 1","value":5.6},{"category":"Cat 2","value":6.56},{"category":"Cat 3","value":6.91},{"category":"Cat 4","value":5.91},{"category":"Cat 5","value":5.65},{"category":"Cat 6","value":5.17}]}]}
```

## 12. `0002141` — cell acc 0%  (type=pie, labels_shown=False, augmented=True)

![0002141](../../../data/synthetic_v0/images/0002141.png)

**Ground truth:**
```csv
category,value
South,680.0
North,16.0
East,425.0
EMEA,17.0
Central,911.0
```

**Prediction:** unparseable — schema[0]: 10 error(s)
```
{"chart_type":"pie","title":"Headcount per Region","x_axis":{"label":null,"unit":null},"y_axis":{"label":null,"unit":null},"series":[{"name":null,"points":[{"category":"South","value":34},{"category":"Central","value":44},{"category":"EMEA","value":1},{"category":"East","value":20},{"category":"North","value":1}]}]}
```

## 13. `0001253` — cell acc 0%  (type=pie, labels_shown=True, augmented=True)

![0001253](../../../data/synthetic_v0/images/0001253.png)

**Ground truth:**
```csv
category,value
Cat 1,1.0
Cat 2,1.0
Cat 3,1.0
Cat 4,1.0
Cat 5,1.0
```

**Prediction:** unparseable — schema[0]: 10 error(s)
```
{"chart_type":"pie","title":"Headcount (Category)","x_axis":{"label":null,"unit":null},"y_axis":{"label":null,"unit":null},"series":[{"name":null,"points":[{"category":"Cat 1","value":1},{"category":"Cat 2","value":1},{"category":"Cat 3","value":1},{"category":"Cat 4","value":1},{"category":"Cat 5","value":1}]}]}
```

## 14. `0000844` — cell acc 0%  (type=pie, labels_shown=False, augmented=True)

![0000844](../../../data/synthetic_v0/images/0000844.png)

**Ground truth:**
```csv
category,value
Brazil,3708.0
Spain,3586.0
Mexico,8650.0
Italy,6669.0
```

**Prediction:** unparseable — schema[0]: 8 error(s)
```
{"chart_type":"pie","title":"Sales Breakdown","x_axis":{"label":null,"unit":null},"y_axis":{"label":null,"unit":null},"series":[{"name":null,"points":[{"category":"Brazil","value":17},{"category":"Italy","value":29},{"category":"Mexico","value":39},{"category":"Spain","value":15}]}]}
```

## 15. `0000386` — cell acc 0%  (type=pie, labels_shown=True, augmented=True)

![0000386](../../../data/synthetic_v0/images/0000386.png)

**Ground truth:**
```csv
category,value
Product D,1.0
Product C,1.0
Product E,1.0
Product F,1.0
```

**Prediction:** unparseable — schema[0]: 8 error(s)
```
{"chart_type":"pie","title":"Product Net Income","x_axis":{"label":null,"unit":null},"y_axis":{"label":null,"unit":null},"series":[{"name":null,"points":[{"category":"Product C","value":1},{"category":"Product D","value":1},{"category":"Product E","value":1},{"category":"Product F","value":1}]}]}
```
