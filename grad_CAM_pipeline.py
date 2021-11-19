# MIT License
#
#Copyright (c) 2017 François Chollet
#Copyright (c) 2020 August Lidfeldt, Simon Åberg, Ludwig Hedlund, Arvid Ekblom
#Copyright (c) 2021 Markus Borg
#
#Permission is hereby granted, free of charge, to any person obtaining a copy
#of this software and associated documentation files (the "Software"), to deal
#in the Software without restriction, including without limitation the rights
#to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
#copies of the Software, and to permit persons to whom the Software is
#furnished to do so, subject to the following conditions:
#
#The above copyright notice and this permission notice shall be included in all
#copies or substantial portions of the Software.
#
#THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
#IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
#FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
#AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
#LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
#OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
#SOFTWARE.

import tensorflow as tf
from tensorflow.keras.models import load_model
from tensorflow.keras.preprocessing import image
from tensorflow.keras.applications.vgg16 import preprocess_input, decode_predictions
from tensorflow.keras.applications.vgg16 import VGG16
from tensorflow.keras.applications.resnet50 import ResNet50
from tensorflow.keras.applications.vgg19 import VGG19
from tensorflow.keras import backend as K
import numpy as np
import cv2
import os
import pathlib

tf.compat.v1.disable_eager_execution()
K.clear_session()
os.environ['KMP_DUPLICATE_LIB_OK']='True'

def setup_model(model_path, weight_path=None, custom_model=False):

    if weight_path != None:
        ## Use for our model
      custom_model = True
      model = load_model(model_path)
      model.load_weights(weight_path)
      print("### Loaded model and weights for: " + model_path)
    elif model_path == 'VGG16':
        ## Use for VGG16
        model = VGG16(weights='imagenet')
    elif model_path == 'ResNet50':
      ## Use for ResNet50
      model = ResNet50(weights='imagenet')
    elif model_path == 'VGG19':
        ## Use for VGG19
        model = VGG19(weights='imagenet')
    else:
        print('### Model not supported')

    model.summary()
    return model, custom_model

def run_pipeline(model_path, weights_path, dataset_path, labels=None, same_size_HD_images=True):
    print('### Model to assess: ' + model_path)
    model, custom_model = setup_model(model_path, weights_path)

    # navigate to input directory and create an output subdirectory
    os.chdir(dataset_path)
    output_dir = 'Grad-CAMs'
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    # Pick out last convolution layer of model
    last_layer_name = ''
    for i in range(1,len(model.layers)+1):
        last_layer_name = model.layers[len(model.layers)-i].name

        if('conv' in last_layer_name):
                print('### Last convolution layer is ' + last_layer_name)
                break;

    last_layer = model.get_layer(last_layer_name)
    no_filters = last_layer.output_shape[3]
    print("### Number of filters at last conv_layer is " + str(last_layer.output_shape[3]))

    combined_gradCAMs = 0
    combined_img = 0
    # loop over images in folder and output
    for curr_file in sorted(os.listdir()): # -1 for heatmaps folder
        # The local path to our target image
        if '.jpg' in curr_file:
            img_path = curr_file
            print('### Found a jpg: ' + curr_file)
        else:
            continue

        # `img` is a PIL image of size 224x224
        img = image.load_img(img_path, target_size=(224, 224))

        # `x` is a float32 Numpy array of shape (224, 224, 3)
        x = image.img_to_array(img)

        # We add a dimension to transform our array into a "batch"
        # of size (1, 224, 224, 3)
        x = np.expand_dims(x, axis=0)

        # Finally we preprocess the batch
        # (this does channel-wise color normalization)
        x_label = x
        #x = preprocess_input(x)

        if not custom_model:
          ## Use for VGG16, VGG19, ResNet50 etc.
          preds = model.predict(x)
          #print('Predicted:', decode_predictions(preds, top=3)[0])
        else:
          ## Use for tunnel model
          preds_label = tf.keras.Sequential([model, tf.keras.layers.Softmax()]).predict(x_label)
          preds = tf.keras.Sequential([model, tf.keras.layers.Softmax()]).predict(x)

        # Load class to predict, will be most likely, change for custom //August
        if custom_model:
            class_label_number = np.argmax(preds_label[0])
        else:
            class_label_number = np.argmax(preds)

        #print(preds)
        #print(class_label_number)

        # This is the entry in the prediction vector of the label that we want to check against
        max_prediction_label_output = model.output[:, class_label_number]

        # The is the output feature map of the `block5_conv3` layer,
        # the last convolutional layer in VGG16
        last_conv_layer = model.get_layer(last_layer_name) ##SHOULD BE specific for model used

        # This is the gradient of the "african elephant" class with regard to
        # the output feature map of `block5_conv3`
        grads = K.gradients(max_prediction_label_output, last_conv_layer.output)[0]

        # This is a vector of shape (512,), where each entry
        # is the mean intensity of the gradient over a specific feature map channel
        pooled_grads = K.mean(grads, axis=(0, 1, 2))

        # This function allows us to access the values of the quantities we just defined:
        # `pooled_grads` and the output feature map of `block5_conv3`,
        # given a sample image
        iterate = K.function([model.input], [pooled_grads, last_conv_layer.output[0]])

        # These are the values of these two quantities, as Numpy arrays,
        # given our sample image of two elephants
        pooled_grads_value, conv_layer_output_value = iterate([x])

        # We multiply each channel in the feature map array
        # by "how important this channel is" with regard to the elephant class
        for i in range(no_filters): ##SHOULD BE 512 for VGG16
            conv_layer_output_value[:, :, i] *= pooled_grads_value[i]

        # The channel-wise mean of the resulting feature map
        # is our heatmap of class activation
        heatmap = np.mean(conv_layer_output_value, axis=-1)

        heatmap = np.maximum(heatmap, 0)
        heatmap /= np.max(heatmap)

        # We use cv2 to load the original image
        img = cv2.imread(img_path)
        last_image = img

        # resize heatmap and images depending on if different or all HD format
        if same_size_HD_images:
            # We resize the heatmap to have the same size as the original image
            heatmap = cv2.resize(heatmap, (img.shape[1], img.shape[0]))
        else:
            img = cv2.resize(img, (500, 500)) #only do if different images
            heatmap = cv2.resize(heatmap, (500, 500)) #only do if different images

        # We convert the heatmap to RGB
        heatmap = np.uint8(255 * heatmap)

        # We apply the heatmap to the original image
        heatmap = cv2.applyColorMap(heatmap, cv2.COLORMAP_JET)

        # Combine heatmaps of all images to one combined heatmap
        if(i == 0):
            file_count = len(os.listdir('.'))
            combined_gradCAMs = heatmap * 0.6/(file_count-1)
            combined_img = img /(file_count-2)
        else:
            file_count = len(os.listdir('.'))
            combined_gradCAMs = heatmap * 0.6/(file_count-1) + combined_gradCAMs
            combined_img = img/(file_count-2) + combined_img

        # 0.4 here is a heatmap intensity factor
        current_image = heatmap * 0.4 + img

        # add prediction certainty to output image
        pred_certainty = int(preds[0][preds[0].argmax()]*1000)/10

        # set label depending on if custom model is used or not
        if custom_model:
            label = str(labels[preds[0].argmax()]) #only custom model with labels at top
        else:
            label = decode_predictions(preds, top=1)[0][0][1] #only for VGG16

        # position text over images
        if same_size_HD_images:
            position = (100,980) # use for HD images, all same size
        else:
            position = (50,450) #use when different image sizes

        cv2.putText(
         current_image, #numpy array on which text is written
         'Prediction ' + str(pred_certainty) + ' % ' + label, #text
         position, #position at which writing has to start
         cv2.FONT_HERSHEY_COMPLEX, #font family
         0.8, #font size
         (255, 255, 255, 255), #font color
         3) #font stroke

        # Save an individual Grad-CAMs in the output folder
        os.chdir(output_dir)
        print('Writing files here: ' + os.getcwd())
        filename = curr_file.split('.jpg')[0] + '-Grad-CAM.jpg'
        cv2.imwrite(filename, current_image)
        os.chdir('..')

    superimposed_img = combined_gradCAMs + combined_img

    # Save the combined Grad-CAMs in the output folder
    os.chdir(output_dir)
    cv2.imwrite('_combined_Grad-CAMs.jpg', superimposed_img)
    cv2.imwrite('_combined_images.jpg', combined_img)
