# -*- coding: utf-8 -*-
"""
Created on Tue Jan 12 14:13:14 2023

@author: AmayaGS
"""

# %%

import torch
import cv2
import numpy as np
from matplotlib import pyplot as plt

from torchvision import transforms, models

from PIL import Image
import openslide as osi

from patchify import patchify
from attention_models import VGG_embedding, GatedAttention

Image.MAX_IMAGE_PIXELS = None

use_gpu = torch.cuda.is_available()
if use_gpu:
    print("Using CUDA")
device = torch.device("cuda:0")

import os, os.path
os.environ["CUDA_LAUNCH_BLOCKING"] = "1"

from PIL import Image

import torch
import torch.nn as nn

from loaders import Loaders
from training_loops import train_embedding, train_att_slides, test_slides

# %%

patch_size = 224
step = 14
slide_level = 1
# main_path = r"C:\Users\Amaya\Documents\PhD\NECCESITY\Slides\QMUL\slides\PATHSSAI ID 10-T59-02.ndpi"
# binary_mask = r"C:/Users/Amaya/Documents/PhD/NECCESITY/Slides/QMUL QuPath\masks\PATHSSAI ID 10-T59-02.png"
main_path = r"C:\Users\Amaya\Documents\PhD\Data\CD68\slides\HOME-R4RA-H998_CD68_S14 - 2021-01-15 13.45.44.tif"
binary_mask = r"C:\Users\Amaya\Documents\PhD\Data\CD68\masks\HOME-R4RA-H998_CD68_S14 - 2021-01-15 13.45.44.png"

# %%

torch.manual_seed(42)
train_fraction = .7
random_state = 2

subset= False

train_batch = 10
test_batch = 1
slide_batch = 1

num_workers = 0
shuffle = False
drop_last = False

train_patches = False
train_slides = False
testing_slides = True

embedding_vector_size = 1024

label = 'Amaya CD68'
patient_id = 'Patient ID'
n_classes=2

if n_classes > 2:
    subtyping=True
else:
    subtyping=False
    

# %%

slide = osi.OpenSlide(main_path)
properties = slide.properties
#adjusted_level = int(slide_level + np.log2(int(properties['openslide.objective-power'])/40))
slide_adjusted_level_dims = slide.level_dimensions[slide_level]
np_img = np.array(slide.read_region((0, 0), slide_level, slide_adjusted_level_dims).convert('RGB'))


# patient_id = 'Patient ID'
# n_classes=2

# if n_classes > 2:
#     subtyping=True
# else:
#     subtyping=False
    
# %%

embedding_weights = r"C:\Users\Amaya\Documents\PhD\Data\CD68\embedding_CD68_" + label + ".pth"
classification_weights = r"C:\Users\Amaya\Documents\PhD\Data\CD68\classification_CD68_" + label + ".pth"

# %%

# make square image

height = np_img.shape[0]
width = np_img.shape[1]

square = (np_img.shape[1] // 224) * 224

dif_h = (height - square) / 2 
dif_w = (width - square) / 2 

h_min = int(0 + dif_h)
h_max = int(np_img.shape[0] - dif_h)

w_min = int(0 + dif_w)
w_max = int(np_img.shape[1] - dif_w)

cropped_image = np_img[h_min:h_max, w_min:w_max]

# %%

np_mask = cv2.imread(binary_mask, 0)
np_mask_resized = cv2.resize(np_mask, (np_img.shape[1], np_img.shape[0]))

# %%

cropped_mask = np_mask_resized[h_min:h_max, w_min:w_max]

# %%

plt.figure(figsize=(50, 50))
plt.subplot(221)
plt.title('Original image', size=65)
plt.imshow(cropped_image)
plt.subplot(222)
plt.title('Predicted heatmap', size=65)
plt.imshow(cropped_mask)
plt.show()

# %%

train_transform = transforms.Compose([
        transforms.Resize((224, 224)),                            
        #transforms.ColorJitter(brightness=0.005, contrast=0.005, saturation=0.005, hue=0.005),
        transforms.RandomChoice([
        transforms.ColorJitter(brightness=0.1),
        transforms.ColorJitter(contrast=0.1), 
        transforms.ColorJitter(saturation=0.1),
        transforms.ColorJitter(hue=0.1)]),
        transforms.RandomHorizontalFlip(),
        transforms.ToTensor(),
        transforms.Normalize((0.5, 0.5, 0.5), (0.5, 0.5, 0.5))      
    ])

test_transform = transforms.Compose([
        transforms.Resize((224, 224)),                            
        transforms.ToTensor(),
        transforms.Normalize((0.5, 0.5, 0.5), (0.5, 0.5, 0.5))      
    ])

# %%

patches_img = patchify(cropped_image, (patch_size, patch_size, 3), step=step)
#patches_mask = patchify(np_mask_resized, (patch_size, patch_size), step=step)

# %%

embedding_net = models.vgg16_bn(pretrained=True)
                
# Freeze training for all layers
for param in embedding_net.parameters():
    param.require_grad = False

# Newly created modules have require_grad=True by default
num_features = embedding_net.classifier[6].in_features
features = list(embedding_net.classifier.children())[:-1] # Remove last layer
features.extend([nn.Linear(num_features, embedding_vector_size)])
features.extend([nn.Dropout(0.5)])
features.extend([nn.Linear(embedding_vector_size, n_classes)]) # Add our layer with n outputs
embedding_net.classifier = nn.Sequential(*features) # Replace the model classifier


# %%

loss = nn.CrossEntropyLoss()

#embedding_net = VGG_embedding(embedding_weights, embedding_vector_size=embedding_vector_size, n_classes=n_classes)
classification_net = GatedAttention(n_classes=n_classes, subtyping=subtyping)

# load pre trained models
embedding_net.load_state_dict(torch.load(embedding_weights), strict=True)    
classification_net.load_state_dict(torch.load(classification_weights), strict=True)

if use_gpu:
    embedding_net.cuda()
    classification_net.cuda()
        
# %%

label = torch.Tensor(1)
patient_embedding = []

embedding_net.eval()
classification_net.eval()

for i in range(patches_img.shape[0]):
    for j in range(patches_img.shape[1]):

        single_patch_img = patches_img[i, j, 0, :, :, :]
        
        if single_patch_img.any() != 255:
            
            tensor = test_transform(Image.fromarray(single_patch_img))
            embedding = embedding_net(tensor.unsqueeze(0).cuda())
            embedding = embedding.detach().to('cpu')
            embedding = embedding.squeeze(0)
            patient_embedding.append(embedding)
            
patient_embedding = torch.stack(patient_embedding)
    
logits, Y_prob, Y_hat, A, instance_dict = classification_net(patient_embedding.cuda(), label=label, instance_eval=False)    


# %%

weights = A.detach().to('cpu').numpy()

# %%

attention_list = []

for i in range(len(weights[0])):
    att_arr = np.full(shape=(patch_size, patch_size), fill_value=weights[0][i])
    attention_list.append(att_arr)
    
#attention_array  = np.concatenate(attention_list, axis=1)
#att_img = np.zeros(np_img.shape[:2])
    
# %%

count = 0
size = int(np.sqrt(weights.size))
step2 = 224
att_img = np.zeros((cropped_image.shape[0], cropped_image.shape[1]))

# for i in range(patches_img.shape[0]):
#     for j in range(patches_img.shape[1]):
        
for i in range(size):
    for j in range(size):        
        
        att_img[i*step: (i*step+step2), j*step: (j*step+step2)] += attention_list[count]
        
        count += 1
        
# %%

#att_img_resized = np.resize(att_img, np_img.shape[:2])

# %%

att_img_crop = cv2.bitwise_and(att_img, att_img, mask=cropped_mask)
att_img_crop[ att_img_crop==0 ] = np.nan
        
# %%

# step1 = 64
# step2 = 5376 # image size
# # range is equal to im_size / 224

# for i in range(24):
#     att_img[i*step1: i*step1 + step1, ] += attention_array[0:64, i*step2 : i*step2 + step2]
    
# %%

att_std = (att_img_crop - att_img_crop.mean()) / (att_img_crop.std())
plt.matshow(att_std*255, cmap=plt.cm.RdBu)
plt.axis('off')
plt.show()


# %%

plt.figure(figsize=(50, 50))
plt.subplot(221)
plt.title('Original image', size=65)
plt.imshow(cropped_image)
plt.subplot(222)
plt.title('Predicted heatmap', size=65)
plt.imshow(att_img_crop, cmap=plt.cm.RdBu)
plt.imshow(cropped_image, alpha=0.4)
plt.show()

# %%

plt.figure(figsize=(50, 50))
plt.title('Predicted heatmap', size=90)
plt.imshow(att_img_crop, cmap=plt.cm.RdBu)
plt.show()

# %%



# %%

plt.figure(figsize=(50, 50))
plt.subplot(221)
plt.title('Original image', size=50)
plt.imshow(img_crop)
plt.subplot(222)
plt.title('Predicted heatmap', size=50)
plt.imshow(att_img_crop, cmap=plt.cm.Reds)
plt.show()

# %%

patch_size = 224
step = 12
slide_level = 1
main_path = r"C:\Users\Amaya\Documents\PhD\NECCESITY\Slides\QMUL\slides\PATHSSAI ID 10-004-01.ndpi"
binary_mask = r"C:\Users\Amaya\Documents\PhD\NECCESITY\Slides\QMUL\masks\PATHSSAI ID 10-004-01.png"

# %%

slide = osi.OpenSlide(main_path)
properties = slide.properties
#adjusted_level = int(slide_level + np.log2(int(properties['openslide.objective-power'])/40))
slide_adjusted_level_dims = slide.level_dimensions[slide_level]
img = slide.read_region((0, 0), slide_level, slide_adjusted_level_dims).convert('RGB')
np_img = np.array(img)


# %%

cv_img =  cv2.cvtColor(np.array(img), cv2.COLOR_BGR2RGB)
# converting to LAB color space
lab= cv2.cvtColor(cv_img, cv2.COLOR_BGR2LAB)
l_channel, a, b = cv2.split(lab)

# Applying CLAHE to L-channel
# feel free to try different values for the limit and grid size:
clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
cl = clahe.apply(l_channel)

# merge the CLAHE enhanced L-channel with the a and b channel
limg = cv2.merge((cl,a,b))

# Converting image from LAB Color model to BGR color spcae
enhanced_img = cv2.cvtColor(limg, cv2.COLOR_LAB2BGR)

# Stacking the original image with the enhanced image
result = np.hstack((img, enhanced_img))
#cv2.imshow('Result', result)

# %%

plt.figure(figsize=(50, 50))
plt.subplot(221)
plt.title('Original image', size=50)
plt.imshow(cv_img)
plt.subplot(222)
plt.title('Predicted heatmap', size=50)
plt.imshow(enhanced_img, cmap=plt.cm.Reds)
plt.show()
