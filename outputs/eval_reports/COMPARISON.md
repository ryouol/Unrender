# Unrender — chart-to-data extraction

Cell = data point recovered within 5% relative error. The **label-free** column is the one that matters: when values aren't printed, the model must read geometry against the axis scale.

## Cell accuracy: labeled vs label-free

| Model | Cell acc (all) | Cell acc (labeled) | Cell acc (label-free) | Gap (lab−free) | Exact chart | Schema ok | N |
| --- | --- | --- | --- | --- | --- | --- | --- |
| anthropic:claude-fable-5 | 88.2% | 92.1% | 84.8% | +7.3 pts | 64.3% | 100.0% | 300 |
| openai:gpt-5.5 | 84.1% | 85.8% | 82.5% | +3.3 pts | 55.5% | 92.6% | 299 |
| gemini:gemini-3.1-pro-preview | 84.3% | 88.5% | 80.7% | +7.9 pts | 56.2% | 84.8% | 256 |

## Label-free cell accuracy by chart type

| Model (label-free cell acc) | bar | grouped_bar | horizontal_bar | line | multi_line | pie | stacked_bar |
| --- | --- | --- | --- | --- | --- | --- | --- |
| anthropic:claude-fable-5 | 84.1% (n=33) | 88.4% (n=23) | 90.7% (n=21) | 91.0% (n=20) | 95.1% (n=19) | 1.2% (n=18) | 82.9% (n=26) |
| openai:gpt-5.5 | 74.9% (n=33) | 85.5% (n=23) | 94.0% (n=21) | 90.3% (n=20) | 93.9% (n=19) | 0.0% (n=18) | 81.2% (n=26) |
| gemini:gemini-3.1-pro-preview | 86.0% (n=29) | 90.5% (n=20) | 4.0% (n=21) | 91.2% (n=17) | 98.3% (n=12) | 0.0% (n=15) | 92.2% (n=24) |
