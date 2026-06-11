# Worst 15 predictions — gemini__gemini-3.1-pro-preview

_Sorted by cell accuracy (within 5%). 257 scored total._


## 1. `0001796` — cell acc 0%  (type=horizontal_bar, labels_shown=False, augmented=True)

![0001796](../../../data/synthetic_v0/images/0001796.png)

**Ground truth:**
```csv
Month,Profit
Jan,87.1
Feb,45.4
Mar,29.7
Apr,28.4
May,32.7
Jun,6.3
Jul,0.8
Aug,38.7
Sep,31.3
Oct,37.9
Nov,95.3
Dec,22.3
```

**Prediction:** unparseable — schema[0]: 12 error(s)
```
{
  "chart_type": "horizontal_bar",
  "title": null,
  "x_axis": {
    "label": "Profit (kWh)",
    "unit": null
  },
  "y_axis": {
    "label": "Month",
    "unit": null
  },
  "series": [
    {
      "name": null,
      "points": [
        {
          "y": "Jan",
          "x": 87.23
        },
        {
          "y": "Feb",
          "x": 45.32
        },
        {
          "y": "Mar",
          "x": 29.57
        },
        {
          "y": "Apr",
          "x": 28.51
        },
        {
          "y": "May",
          "x": 32.77
        },
        {
          "y": "Jun",
          "x":
```

## 2. `0003952` — cell acc 0%  (type=horizontal_bar, labels_shown=True, augmented=True)

![0003952](../../../data/synthetic_v0/images/0003952.png)

**Ground truth:**
```csv
Month,Throughput
Jan,31322.0
Feb,48013.0
Mar,64944.0
Apr,48791.0
May,60186.0
Jun,44402.0
Jul,16986.0
Aug,34764.0
Sep,39633.0
Oct,87504.0
Nov,96975.0
```

**Prediction:** unparseable — schema[0]: 11 error(s)
```
{
  "chart_type": "horizontal_bar",
  "title": "Annual Throughput",
  "x_axis": {
    "label": "Throughput",
    "unit": null
  },
  "y_axis": {
    "label": "Month",
    "unit": null
  },
  "series": [
    {
      "name": null,
      "points": [
        {
          "x": 31.322,
          "y": "Jan"
        },
        {
          "x": 48.013,
          "y": "Feb"
        },
        {
          "x": 64.944,
          "y": "Mar"
        },
        {
          "x": 48.791,
          "y": "Apr"
        },
        {
          "x": 60.186,
          "y": "May"
        },
        {
          "x": 44.
```

## 3. `0000803` — cell acc 0%  (type=horizontal_bar, labels_shown=True, augmented=True)

![0000803](../../../data/synthetic_v0/images/0000803.png)

**Ground truth:**
```csv
Year,Sales
2009,-404.0
2010,267.0
2011,955.0
2012,812.0
2013,459.0
2014,690.0
2015,839.0
2016,217.0
2017,920.0
2018,-319.0
2019,73.0
```

**Prediction:**
```csv
Sales,Year
-404,2009.0
267,2010.0
955,2011.0
812,2012.0
459,2013.0
690,2014.0
839,2015.0
217,2016.0
920,2017.0
-319,2018.0
73,2019.0
```

## 4. `0003582` — cell acc 0%  (type=horizontal_bar, labels_shown=False, augmented=True)

![0003582](../../../data/synthetic_v0/images/0003582.png)

**Ground truth:**
```csv
Product,Production
Product F,486004.0
Product A,322128.0
Product D,46133.0
Product B,728083.0
Product C,258807.0
Product E,367790.0
Product G,574408.0
Product H,127837.0
Product I,324789.0
Product J,497820.0
```

**Prediction:** unparseable — schema[0]: 10 error(s)
```
{
  "chart_type": "horizontal_bar",
  "title": "Production Overview",
  "x_axis": {
    "label": "Production (mm)",
    "unit": null
  },
  "y_axis": {
    "label": "Product",
    "unit": null
  },
  "series": [
    {
      "name": null,
      "points": [
        {
          "x": 487213.9113649524,
          "y": "Product F"
        },
        {
          "x": 322470.8354415865,
          "y": "Product A"
        },
        {
          "x": 46554.49250024479,
          "y": "Product D"
        },
        {
          "x": 727786.1517409957,
          "y": "Product B"
        },
        {
      
```

## 5. `0004397` — cell acc 0%  (type=horizontal_bar, labels_shown=True, augmented=True)

![0004397](../../../data/synthetic_v0/images/0004397.png)

**Ground truth:**
```csv
Region,value
EMEA,0.0
North,1.0
LATAM,1.0
East,1.0
West,1.0
Central,0.0
South,1.0
APAC,1.0
Region 9,0.0
Region 10,0.0
```

**Prediction:** unparseable — schema[0]: 10 error(s)
```
{
  "chart_type": "horizontal_bar",
  "title": "Rainfall Breakdown",
  "x_axis": {
    "label": null,
    "unit": null
  },
  "y_axis": {
    "label": "Region",
    "unit": null
  },
  "series": [
    {
      "name": null,
      "points": [
        {
          "y": "Region 10",
          "x": 0
        },
        {
          "y": "Region 9",
          "x": 0
        },
        {
          "y": "APAC",
          "x": 1
        },
        {
          "y": "South",
          "x": 1
        },
        {
          "y": "Central",
          "x": 0
        },
        {
          "y": "West",
        
```

## 6. `0000674` — cell acc 0%  (type=horizontal_bar, labels_shown=False, augmented=True)

![0000674](../../../data/synthetic_v0/images/0000674.png)

**Ground truth:**
```csv
x,Throughput
Q2 2018,2865.9
Q3 2018,68804.7
Q4 2018,96905.8
Q1 2019,33535.3
Q2 2019,62022.5
Q3 2019,74635.6
Q4 2019,51847.1
Q1 2020,80967.9
Q2 2020,52899.4
Q3 2020,90805.9
```

**Prediction:** unparseable — schema[0]: 10 error(s)
```
{
  "chart_type": "horizontal_bar",
  "title": "Total Throughput by Quarter",
  "x_axis": {
    "label": "Throughput",
    "unit": null
  },
  "y_axis": {
    "label": null,
    "unit": null
  },
  "series": [
    {
      "name": null,
      "points": [
        {
          "y": "Q3 2020",
          "x": 90786
        },
        {
          "y": "Q2 2020",
          "x": 52912
        },
        {
          "y": "Q1 2020",
          "x": 80922
        },
        {
          "y": "Q4 2019",
          "x": 51838
        },
        {
          "y": "Q3 2019",
          "x": 74581
        },
      
```

## 7. `0003837` — cell acc 0%  (type=horizontal_bar, labels_shown=False, augmented=True)

![0003837](../../../data/synthetic_v0/images/0003837.png)

**Ground truth:**
```csv
Country,value
Brazil,4.8
Germany,6.2
France,0.2
Japan,-4.4
Italy,1.2
UK,-2.4
Mexico,4.5
India,-2.6
Canada,8.3
USA,3.0
```

**Prediction:** unparseable — schema[0]: 10 error(s)
```
{
  "chart_type": "horizontal_bar",
  "title": "Latency (Country)",
  "x_axis": {
    "label": null,
    "unit": null
  },
  "y_axis": {
    "label": "Country",
    "unit": null
  },
  "series": [
    {
      "name": "Latency",
      "points": [
        {
          "y": "USA",
          "x": 3
        },
        {
          "y": "Canada",
          "x": 8.3
        },
        {
          "y": "India",
          "x": -2.6
        },
        {
          "y": "Mexico",
          "x": 4.5
        },
        {
          "y": "UK",
          "x": -2.4
        },
        {
          "y": "Italy",
   
```

## 8. `0004718` — cell acc 0%  (type=horizontal_bar, labels_shown=False, augmented=True)

![0004718](../../../data/synthetic_v0/images/0004718.png)

**Ground truth:**
```csv
Month,Downloads
Jan,102862.2
Feb,757265.8
Mar,691125.1
Apr,518973.0
May,415199.6
Jun,887506.1
Jul,830047.4
Aug,520094.9
Sep,817668.9
Oct,615787.8
```

**Prediction:** unparseable — schema[0]: 10 error(s)
```
{
  "chart_type": "horizontal_bar",
  "title": "Month Downloads",
  "x_axis": {
    "label": "Downloads",
    "unit": null
  },
  "y_axis": {
    "label": "Month",
    "unit": null
  },
  "series": [
    {
      "name": null,
      "points": [
        {
          "x": 103225,
          "y": "Jan"
        },
        {
          "x": 758064,
          "y": "Feb"
        },
        {
          "x": 690322,
          "y": "Mar"
        },
        {
          "x": 519354,
          "y": "Apr"
        },
        {
          "x": 416129,
          "y": "May"
        },
        {
          "x": 887096
```

## 9. `0003632` — cell acc 0%  (type=horizontal_bar, labels_shown=False, augmented=False)

![0003632](../../../data/synthetic_v0/images/0003632.png)

**Ground truth:**
```csv
x,Rainfall
Cat 1,0.74
Cat 2,0.08
Cat 3,0.5
Cat 4,0.51
Cat 5,0.8
Cat 6,0.81
Cat 7,0.58
Cat 8,0.93
Cat 9,0.07
```

**Prediction:** unparseable — schema[0]: 9 error(s)
```
{
  "chart_type": "horizontal_bar",
  "title": null,
  "x_axis": {
    "label": "Rainfall",
    "unit": null
  },
  "y_axis": {
    "label": null,
    "unit": null
  },
  "series": [
    {
      "name": null,
      "points": [
        {
          "y": "Cat 1",
          "x": 0.74
        },
        {
          "y": "Cat 2",
          "x": 0.08
        },
        {
          "y": "Cat 3",
          "x": 0.5
        },
        {
          "y": "Cat 4",
          "x": 0.51
        },
        {
          "y": "Cat 5",
          "x": 0.8
        },
        {
          "y": "Cat 6",
          "x": 0
```

## 10. `0003716` — cell acc 0%  (type=horizontal_bar, labels_shown=False, augmented=False)

![0003716](../../../data/synthetic_v0/images/0003716.png)

**Ground truth:**
```csv
x,Latency
Q2 2016,4081.0
Q3 2016,3565.0
Q4 2016,7669.0
Q1 2017,9836.0
Q2 2017,77.0
Q3 2017,6331.0
Q4 2017,8147.0
Q1 2018,8428.0
Q2 2018,7220.0
```

**Prediction:** unparseable — schema[0]: 9 error(s)
```
{
  "chart_type": "horizontal_bar",
  "title": "Latency Overview",
  "x_axis": {
    "label": "Latency (ms)",
    "unit": "ms"
  },
  "y_axis": {
    "label": null,
    "unit": null
  },
  "series": [
    {
      "name": null,
      "points": [
        {
          "y": "Q2 2016",
          "x": 4082
        },
        {
          "y": "Q3 2016",
          "x": 3571
        },
        {
          "y": "Q4 2016",
          "x": 7653
        },
        {
          "y": "Q1 2017",
          "x": 9846
        },
        {
          "y": "Q2 2017",
          "x": 51
        },
        {
          "y
```

## 11. `0004262` — cell acc 0%  (type=horizontal_bar, labels_shown=False, augmented=True)

![0004262](../../../data/synthetic_v0/images/0004262.png)

**Ground truth:**
```csv
Month,Revenue
Feb,494.0
Mar,2288.0
Apr,3075.0
May,9367.0
Jun,1404.0
Jul,-2472.0
Aug,6809.0
Sep,9678.0
Oct,-627.0
```

**Prediction:** unparseable — schema[0]: 9 error(s)
```
{
  "chart_type": "horizontal_bar",
  "title": null,
  "x_axis": {
    "label": "Revenue",
    "unit": null
  },
  "y_axis": {
    "label": "Month",
    "unit": null
  },
  "series": [
    {
      "name": null,
      "points": [
        {
          "y": "Feb",
          "x": 500
        },
        {
          "y": "Mar",
          "x": 2250
        },
        {
          "y": "Apr",
          "x": 3000
        },
        {
          "y": "May",
          "x": 9300
        },
        {
          "y": "Jun",
          "x": 1300
        },
        {
          "y": "Jul",
          "x": -2600
    
```

## 12. `0004612` — cell acc 0%  (type=horizontal_bar, labels_shown=True, augmented=True)

![0004612](../../../data/synthetic_v0/images/0004612.png)

**Ground truth:**
```csv
x,Expenses
Cat 1,7.0
Cat 2,3.0
Cat 3,8.0
Cat 4,6.0
Cat 5,1.0
Cat 6,8.0
Cat 7,6.0
Cat 8,6.0
Cat 9,10.0
```

**Prediction:** unparseable — schema[0]: 9 error(s)
```
{
  "chart_type": "horizontal_bar",
  "title": "Expenses per Category",
  "x_axis": {
    "label": "Expenses",
    "unit": null
  },
  "y_axis": {
    "label": null,
    "unit": null
  },
  "series": [
    {
      "name": null,
      "points": [
        {
          "y": "Cat 1",
          "x": 7
        },
        {
          "y": "Cat 2",
          "x": 3
        },
        {
          "y": "Cat 3",
          "x": 8
        },
        {
          "y": "Cat 4",
          "x": 6
        },
        {
          "y": "Cat 5",
          "x": 1
        },
        {
          "y": "Cat 6",
          
```

## 13. `0001147` — cell acc 0%  (type=horizontal_bar, labels_shown=True, augmented=True)

![0001147](../../../data/synthetic_v0/images/0001147.png)

**Ground truth:**
```csv
Month,Production
May,0.0
Jun,0.0
Jul,0.0
Aug,1.0
Sep,1.0
Oct,1.0
Nov,0.0
Dec,1.0
```

**Prediction:** unparseable — schema[0]: 8 error(s)
```
{
  "chart_type": "horizontal_bar",
  "title": "Month Production",
  "x_axis": {
    "label": "Production",
    "unit": null
  },
  "y_axis": {
    "label": "Month",
    "unit": null
  },
  "series": [
    {
      "name": null,
      "points": [
        {
          "x": 0,
          "y": "May"
        },
        {
          "x": 0,
          "y": "Jun"
        },
        {
          "x": 0,
          "y": "Jul"
        },
        {
          "x": 1,
          "y": "Aug"
        },
        {
          "x": 1,
          "y": "Sep"
        },
        {
          "x": 1,
          "y": "Oct"
     
```

## 14. `0003186` — cell acc 0%  (type=horizontal_bar, labels_shown=False, augmented=True)

![0003186](../../../data/synthetic_v0/images/0003186.png)

**Ground truth:**
```csv
Quarter,Users
Q1 2016,59209.62
Q2 2016,8232.53
Q3 2016,4090.8
Q4 2016,70783.49
Q1 2017,26935.63
Q2 2017,85728.94
Q3 2017,2481.45
Q4 2017,75008.04
```

**Prediction:** unparseable — schema[0]: 8 error(s)
```
{
  "chart_type": "horizontal_bar",
  "title": null,
  "x_axis": {
    "label": "Users (USD)",
    "unit": null
  },
  "y_axis": {
    "label": "Quarter",
    "unit": null
  },
  "series": [
    {
      "name": null,
      "points": [
        {
          "y": "Q1 2016",
          "x": 58913
        },
        {
          "y": "Q2 2016",
          "x": 7826
        },
        {
          "y": "Q3 2016",
          "x": 3260
        },
        {
          "y": "Q4 2016",
          "x": 69782
        },
        {
          "y": "Q1 2017",
          "x": 25869
        },
        {
          "y": "Q
```

## 15. `0003884` — cell acc 0%  (type=horizontal_bar, labels_shown=True, augmented=True)

![0003884](../../../data/synthetic_v0/images/0003884.png)

**Ground truth:**
```csv
Region,Cost
West,3.76
EMEA,48.91
LATAM,57.2
South,1.65
APAC,9.73
East,59.76
North,-12.1
Central,-10.5
```

**Prediction:** unparseable — schema[0]: 8 error(s)
```
{
  "chart_type": "horizontal_bar",
  "title": "Total Cost by Region",
  "x_axis": {
    "label": "Cost",
    "unit": null
  },
  "y_axis": {
    "label": "Region",
    "unit": null
  },
  "series": [
    {
      "name": null,
      "points": [
        {
          "x": 3.76,
          "y": "West"
        },
        {
          "x": 48.91,
          "y": "EMEA"
        },
        {
          "x": 57.2,
          "y": "LATAM"
        },
        {
          "x": 1.65,
          "y": "South"
        },
        {
          "x": 9.73,
          "y": "APAC"
        },
        {
          "x": 59.76,

```
