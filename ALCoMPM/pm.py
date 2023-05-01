# -*- coding: utf-8 -*-
"""PM.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/1nmDH6Wm-7jaHjRUt6RIsNsACyQ74Fgm4
"""

# from google.colab import drive
# drive.mount('/content/drive/')

import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader

import os

# Root path
# path = "/content/drive/MyDrive/CoMPM/"
path = "/workspace/CoMPM/"

# Path for training PM and CoM
train_path = path + "text_test.txt"
dev_path = path + "text_dev.txt"
test_path = path + "text_train.txt"

# Training

"""Dataset Loading"""
dataclass = "emotion"
batch_size = 1
sample = 1.0

num_workers = 2

clsNum = 7

# !pip install transformers

from transformers import AutoModel, AutoTokenizer

# PM
roberta_model = AutoModel.from_pretrained("klue/roberta-large")
roberta_tokenizer = AutoTokenizer.from_pretrained("klue/roberta-large")

# CoM
bert_model = AutoModel.from_pretrained("monologg/kobigbird-bert-base")
bert_tokenizer = AutoTokenizer.from_pretrained("monologg/kobigbird-bert-base")

def padding(ids_list, tokenizer):
    max_len = 0
    for ids in ids_list:
        if len(ids) > max_len:
            max_len = len(ids)
    
    pad_ids = []
    for ids in ids_list:
        pad_len = max_len-len(ids)
        add_ids = [tokenizer.pad_token_id for _ in range(pad_len)]
        
        pad_ids.append(ids+add_ids)
    
    return torch.tensor(pad_ids)

def encode_right_truncated(text, tokenizer, max_length=4095):
    tokenized = tokenizer.tokenize(text)
    truncated = tokenized[-max_length:]    
    ids = tokenizer.convert_tokens_to_ids(truncated)
    
    return [tokenizer.cls_token_id] + ids

def CELoss(pred_outs, labels):
    """
        pred_outs: [batch, clsNum]
        labels: [batch]
    """
    loss = nn.CrossEntropyLoss()
    loss_val = loss(pred_outs, labels)
    return loss_val

def _CalACC(model, dataloader):
    model.eval()
    correct = 0
    label_list = []
    pred_list = []
    
    # label arragne
    with torch.no_grad():
        for i_batch, data in enumerate(dataloader):            
            """Prediction"""
            batch_input_tokens, batch_labels = data
            batch_input_tokens, batch_labels = batch_input_tokens.cuda(), batch_labels.cuda()
            
            pred_logits = model(batch_input_tokens) # (1, clsNum)
            
            """Calculation"""    
            pred_label = pred_logits.argmax(1).item()
            true_label = batch_labels.item()
            
            pred_list.append(pred_label)
            label_list.append(true_label)
            if pred_label == true_label:
                correct += 1
        acc = correct/len(dataloader)
    return acc, pred_list, label_list

def _SaveModel(model, path):
    if not os.path.exists(path):
        os.makedirs(path)
    torch.save(model.state_dict(), os.path.join(path, 'model.pt'))

class PM_KEMDy20_loader(Dataset):
    def __init__(self, txt_file, dataclass):
        self.dialogs = []
        
        f = open(txt_file, 'r', encoding = "utf-8")
        dataset = f.readlines()
        f.close()
        
        temp_speakerList = []
        self.speakerNum = []
        # 'anger', 'disgust', 'fear', 'joy', 'neutral', 'sadness', 'surprise'
        emodict = {'angry': "angry", 'disgust': "disgust", 'fear': "fear", 'happy': "happy", 'neutral': "neutral", 'sad': "sad", 'surprise': 'surprise'}
        self.sentidict = {'positive': ["happy"], 'negative': ["angry", "disgust", "fear", "sadness"], 'neutral': ["neutral", "surprise"]}
        self.emoSet = set(emodict.values())
        self.sentiSet = set()
        for i, data in enumerate(dataset):
            if i < 2:
                continue
            if data == '\n' and len(self.dialogs) > 0:
                continue
            speaker, utt, emo, senti = data.strip().split('\t')
            
            self.dialogs.append([utt, emodict[emo], senti])
            self.emoSet.add(emodict[emo])
            self.sentiSet.add(senti)
        
        self.emoList = sorted(self.emoSet)  
        self.sentiList = sorted(self.sentiSet)
        if dataclass == 'emotion':
            self.labelList = self.emoList
        else:
            self.labelList = self.sentiList        
        self.speakerNum.append(len(temp_speakerList))
        
    def __len__(self):
        return len(self.dialogs)

    def __getitem__(self, idx):
        return self.dialogs[idx], self.labelList, self.sentidict

def PM_make_batch(sessions):
    batch_input, batch_labels = [], []
    for session in sessions:
        data = session[0]
        label_list = session[1]
        
        utt, emotion, sentiment = data        
        batch_input.append(encode_right_truncated(utt.strip(), roberta_tokenizer))
        
        if len(label_list) > 3:
            label_ind = label_list.index(emotion)
        else:
            label_ind = label_list.index(sentiment)
        batch_labels.append(label_ind)
    
    batch_input_tokens = padding(batch_input, roberta_tokenizer)
    batch_labels = torch.tensor(batch_labels)    
    
    return batch_input_tokens, batch_labels

class PM_ERC_model(nn.Module):
    def __init__(self, clsNum):
        super(PM_ERC_model, self).__init__()
        self.gpu = True
        
        """Model Setting"""        

        self.context_model = roberta_model
        tokenizer = roberta_tokenizer

        tokenizer.add_special_tokens({'cls_token': '[CLS]', 'pad_token': '[PAD]'})            
        # tokenizer.add_special_tokens(special_tokens)
        
        self.context_model.resize_token_embeddings(len(tokenizer))
        self.hiddenDim = 1024 # self.context_model.config.hidden_size        
            
        """score"""
        self.W = nn.Linear(self.hiddenDim, clsNum)

    def forward(self, batch_input_tokens):
        """
            batch_input_tokens: (batch, len)
        """
        batch_context_output = self.context_model(batch_input_tokens).last_hidden_state[:,0,:] # (batch, 1024)
        context_logit = self.W(batch_context_output) # (batch, clsNum)        
        return context_logit

class CoM_KEMDy20_loader(Dataset):
    def __init__(self, txt_file, dataclass):
        self.dialogs = []
        
        f = open(txt_file, 'r')
        dataset = f.readlines()
        f.close()
        
        temp_speakerList = []
        context = []
        context_speaker = []
        self.speakerNum = []
        # 'anger', 'disgust', 'fear', 'joy', 'neutral', 'sadness', 'surprise'
        emodict = {'angry': "angry", 'disgust': "disgust", 'fear': "fear", 'happy': "happy", 'neutral': "neutral", 'sad': "sad", 'surprise': 'surprise'}
        self.sentidict = {'positive': ["happy"], 'negative': ["angry", "disgust", "fear", "sadness"], 'neutral': ["neutral", "surprise"]}
        self.emoSet = set(emodict.values())
        self.sentiSet = set()
        for i, data in enumerate(dataset):
            if i < 2:
                continue
            if data == '\n' and len(self.dialogs) > 0:
                self.speakerNum.append(len(temp_speakerList))
                temp_speakerList = []
                context = []
                context_speaker = []
                continue
            speaker, utt, emo, senti = data.strip().split('\t')
            context.append(utt)
            if speaker not in temp_speakerList:
                temp_speakerList.append(speaker)
            speakerCLS = temp_speakerList.index(speaker)
            context_speaker.append(speakerCLS)
            
            self.dialogs.append([context_speaker[:], context[:], emodict[emo], senti])
            self.emoSet.add(emodict[emo])
            self.sentiSet.add(senti)
        
        self.emoList = sorted(self.emoSet)  
        self.sentiList = sorted(self.sentiSet)
        if dataclass == 'emotion':
            self.labelList = self.emoList
        else:
            self.labelList = self.sentiList        
        self.speakerNum.append(len(temp_speakerList))
        
    def __len__(self):
        return len(self.dialogs)

    def __getitem__(self, idx):
        return self.dialogs[idx], self.labelList, self.sentidict

def CoM_make_batch(sessions):
    batch_input, batch_labels = [], []
    for session in sessions:
        data = session[0]
        label_list = session[1]
        
        context_speaker, context, emotion, sentiment = data
        now_speaker = context_speaker[-1]
        speaker_utt_list = []
        
        inputString = ""
        for turn, (speaker, utt) in enumerate(zip(context_speaker, context)):
            inputString += '<s' + str(speaker+1) + '> ' # s1, s2, s3...
            inputString += utt + " "
            
            if turn<len(context_speaker)-1 and speaker == now_speaker:
                speaker_utt_list.append(encode_right_truncated(utt, bert_tokenizer))
        
        concat_string = inputString.strip()
        batch_input.append(encode_right_truncated(concat_string, bert_tokenizer))
        
        if len(label_list) > 3:
            label_ind = label_list.index(emotion)
        else:
            label_ind = label_list.index(sentiment)
        batch_labels.append(label_ind)        
    
    batch_input_tokens = padding(batch_input, bert_tokenizer)
    batch_labels = torch.tensor(batch_labels)
    
    return batch_input_tokens, batch_labels

class CoM_ERC_model(nn.Module):
    def __init__(self, clsNum):
        super(CoM_ERC_model, self).__init__()
        self.gpu = True
        
        """Model Setting"""
        # model_path = '/data/project/rw/rung/model/'+model_type
        self.model = bert_model
        tokenizer = bert_tokenizer
        
        tokenizer.add_special_tokens({'cls_token': '[CLS]', 'pad_token': '[PAD]'})
        # tokenizer.add_special_tokens(special_tokens)
        self.model.resize_token_embeddings(len(tokenizer))
        self.hiddenDim = 768 # self.model.config.hidden_size
            
        """score"""
        self.W = nn.Linear(self.hiddenDim, clsNum)

    def forward(self, batch_input_tokens):
        """
            batch_input_tokens: (batch, len)
        """

        batch_context_output = self.model(batch_input_tokens).last_hidden_state[:,0,:] # (batch, 1024)
        context_logit = self.W(batch_context_output) # (batch, clsNum)
        
        return context_logit

"""# PM

"""

model = PM_ERC_model(clsNum)
model = model.cuda()
model.train()

train_dataset = PM_KEMDy20_loader(train_path, dataclass)
train_dataloader = DataLoader(train_dataset, batch_size=batch_size, shuffle=True, num_workers=num_workers, collate_fn=PM_make_batch)
train_sample_num = int(len(train_dataset)*sample)

test_dataset = PM_KEMDy20_loader(test_path, dataclass)
test_dataloader = DataLoader(test_dataset, batch_size=1, shuffle=False, num_workers=num_workers, collate_fn=PM_make_batch)

dev_dataset = PM_KEMDy20_loader(dev_path, dataclass)
dev_dataloader = DataLoader(dev_dataset, batch_size=1, shuffle=False, num_workers=num_workers, collate_fn=PM_make_batch)

"""Training Setting"""

from transformers import get_linear_schedule_with_warmup

training_epochs = 10
save_term = int(training_epochs/5)
max_grad_norm = 10
lr = 1e-5
num_training_steps = len(train_dataset)*training_epochs
num_warmup_steps = len(train_dataset)
optimizer = torch.optim.AdamW(model.parameters(), lr=lr) # , eps=1e-06, weight_decay=0.01
scheduler = get_linear_schedule_with_warmup(optimizer, num_warmup_steps=num_warmup_steps, num_training_steps=num_training_steps)

save_path = os.path.join(path, "PM/")

"""Input & Label Setting"""
best_dev_fscore, best_test_fscore = 0, 0
best_dev_fscore_macro, best_dev_fscore_micro, best_test_fscore_macro, best_test_fscore_micro = 0, 0, 0, 0    
best_epoch = 0

from tqdm import tqdm
from sklearn.metrics import precision_recall_fscore_support

for epoch in tqdm(range(training_epochs)):
    model.train() 
    for i_batch, data in enumerate(train_dataloader):
        if i_batch > train_sample_num:
            print(i_batch, train_sample_num)
            break
        
        """Prediction"""
        batch_input_tokens, batch_labels = data
        batch_input_tokens, batch_labels = batch_input_tokens.cuda(), batch_labels.cuda()
        
        pred_logits = model(batch_input_tokens)

        """Loss calculation & training"""
        loss_val = CELoss(pred_logits, batch_labels)
        
        loss_val.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), max_grad_norm)  # Gradient clipping is not in AdamW anymore (so you can use amp without issue)
        optimizer.step()
        scheduler.step()
        optimizer.zero_grad()
        
    """Dev & Test evaluation"""
    model.eval()        
    dev_acc, dev_pred_list, dev_label_list = _CalACC(model, dev_dataloader)
    dev_pre, dev_rec, dev_fbeta, _ = precision_recall_fscore_support(dev_label_list, dev_pred_list, average='weighted')

    """Best Score & Model Save"""
    if dev_fbeta > best_dev_fscore:
        best_dev_fscore = dev_fbeta
        
        test_acc, test_pred_list, test_label_list = _CalACC(model, test_dataloader)
        test_pre, test_rec, test_fbeta, _ = precision_recall_fscore_support(test_label_list, test_pred_list, average='weighted')                
        
        best_epoch = epoch
        _SaveModel(model, save_path)
    
    print('Epoch: {}'.format(epoch))
    print('Devleopment ## accuracy: {}, precision: {}, recall: {}, fscore: {}'.format(dev_acc, dev_pre, dev_rec, dev_fbeta))
    print()
    
print('Final Fscore ## test-accuracy: {}, test-fscore: {}, test_epoch: {}'.format(test_acc, test_fbeta, best_epoch))