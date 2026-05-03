Classification:
	Dataset:
		https://cvit.iiit.ac.in/usodi/Docfig.php - Download and extract the dataset.
		Replace annotation directory with the downloaded annotations: ie. /classification/dataset/annotation/train.txt
		Replace images directory with the downloaded images: ie. /classification/dataset/images/

	DocFigure_class_labels:
		How we decided to split the 28 different categories from the dataset into our 7

	classification.ipynb:
		ipynb file to do the finetuning of the resnet-50

	remap_labels.py
		changing the classification from the original dataset to the wanted classes
							
Alt Text Generation:
	Dataset:
		https://github.com/allenai/hci-alt-texts - Download and extract the dataset from the link on this github
		Replace images directory with the downloaded images: ie. /alttext/dataset/images/
		Keep the JSONL fine in dataset: ie. /alttext/datasets/hci-alt-text-dataset-20220918.JSONL
	Finetune:
		base_model_generation.py:
			testing not finetuned alt text generation
		finetune_paligemma2.py:
			How to Run: 
			For diagrams: python3 finetune_paligemma2.py --figure-class "diagram"
			For graph: python3 finetune_paligemma2.py --figure-class "graph"
			For photograph: python3 finetune_paligemma2.py --figure-class "photograph"
		text_generation.py:
			Generates text given an image inside the want_generation directory and a given finetuned path
		paligemma-alt-text-lora:
			Older directory just testing finetuning all the data. Does not account for the tag system. Ignore
		want_generation:
			Directory for storing the wanted images of generation
		classify_hci_dataset.py:
			Classifies the alt text dataset with the finetuned classification model.