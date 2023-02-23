from os.path import isfile, join
from os import listdir
import logging as logging
from ssl import ALERT_DESCRIPTION_PROTOCOL_VERSION
import pandas as pd
import math
from Controller.controller import Controller
from Hardware.vdpelement import VDPElement
from constants import *
from PerformanceMetrics.metrics import Metrics
from Hardware.VDP import VDP
from Hardware.Pool import Pool
from Hardware.stochastic_MRRVDP import Stocastic_MRRVDP
from Hardware.MRRVDP import MRRVDP
from Hardware.Adder import Adder
from Hardware.Accelerator import Accelerator
from Exceptions.AcceleratorExceptions import VDPElementException
from ast import Str
import os.path
import sys
import numpy as np
sys.path.append(os.path.join(os.path.dirname(__file__), '.'))


def im2col(X,conv1, stride, pad):
    # Padding
    X_padded = np.pad(X, ((0,0), (0,0), (pad, pad), (pad, pad)), mode='constant')
    X = X_padded
    new_height = int((X.shape[2]+(2*pad)-(conv1.shape[2]))/stride)+1
    new_width =  int((X.shape[3]+(2*pad)-(conv1.shape[3]))/stride)+1
    im2col_vector = np.zeros((X.shape[1]*conv1.shape[2]*conv1.shape[3],new_width*new_height*X.shape[0]))
    c = 0
    for position in range(X.shape[0]):

        image_position = X[position,:,:,:]
        for height in range(0,image_position.shape[1],stride):
            image_rectangle = image_position[:,height:height+conv1.shape[2],:]
            if image_rectangle.shape[1]<conv1.shape[2]:
                continue
            else:
                for width in range(0,image_rectangle.shape[2],stride):
                    image_square = image_rectangle[:,:,width:width+conv1.shape[3]]
                    if image_square.shape[2]<conv1.shape[3]:
                        continue
                    else:
                        im2col_vector[:,c:c+1]=image_square.reshape(-1,1)
                        c = c+1         
            
    return(im2col_vector)

logger = logging.getLogger("__main__")
logger.setLevel(logging.INFO)

# * Input model files column headers constants
LAYER_TYPE = "name"
MODEL_NAME = "model_name"
KERNEL_DEPTH = "kernel_depth"
KERNEL_HEIGHT = "kernel_height"
KERNEL_WIDTH = "kernel_width"
TENSOR_COUNT = "tensor_count"
INPUT_SHAPE = "input_shape"
OUTPUT_SHAPE = "output_shape"
TENSOR_SHAPE = "tensor_shape"
INPUT_HEIGHT = "input_height"
INPUT_WIDTH = "input_width"
INPUT_DEPTH = "input_depth"
OUTPUT_HEIGHT = "output_height"
OUTPUT_WIDTH = "output_width"
OUTPUT_DEPTH = "output_depth"


# * performance metrics
HARDWARE_UTILIZATION = "hardware_utilization"
TOTAL_LATENCY = "total_latency"
TOTAL_DYNAMIC_ENERGY = "total_dynamic_energy"
TOTAL_STATIC_POWER = "total_static_power"
CONFIG = "config"
AUTO_RECONFIG = "auto_reconfig"
SUPPORTED_LAYER_LIST = "supported_layer_list"
AREA = "area"
FPS = "fps"
FPS_PER_W = "fps_per_w"
FPS_PER_W_PER_AREA = "fps_per_w_per_area"
EDP = "edp"
CONV_TYPE = "conv_type"
VDP_TYPE = 'vdp_type'
NAME = 'name'
POWER = 'power'

# * VDP element constants
ring_radius = 4.55E-6
pitch = 5E-6
vdp_units = []
# * ADC area and power changes with BR {BR: {area: , power: }}}
adc_area_power = { 
    0.008: {AREA: 0.04, POWER: 14.3},
    0.112: {AREA: 0.0594, POWER: 24.1},
    5.000: {AREA: 0.103, POWER: 29},
                  1.000: {AREA: 0.014, POWER: 10.4},
                  10.000:{AREA:0.00017, POWER: 0.2}}
dac_area_power = {
   0.008: {AREA: 0.04, POWER: 14.3},
    0.112: {AREA: 0.06, POWER: 26},
    5: {AREA: 0.06, POWER: 26},
    1: {AREA: 0.06, POWER: 26},
    10: {AREA: 0.06, POWER: 26}
                  }
PCA_ACC_Count = 1

def run(modelName, cnnModelDirectory, accelerator_config, required_precision=8):

    print("The Model being Processed---->", modelName)
    print("Simulator Excution Begin")
    print("Start Creating Accelerator")

    run_config = accelerator_config

    result = {}
    print("Accelerator configuration", run_config)
    # * Declaration of all the objects needed for excuting a CNN model on to the accelerator to find latency and hardware utilization
    accelerator = Accelerator()
    adder = Adder()
    pool = Pool()
    

    controller = Controller()
    metrics = Metrics()

    # * Creating MRR VDP units with the vdp configurations and adding it to accelerator
    for vdp_config in run_config:
        vdp_type = vdp_config[VDP_TYPE]
        accelerator.set_vdp_type(vdp_type)
        accelerator.set_acc_type(vdp_config.get(ACC_TYPE))
        
        # * Peripheral Parameters assigning
        adder.latency = (1/vdp_config.get(BITRATE))*1e-9
        accelerator.add_pheripheral(ADDER, adder)
        
        accelerator.add_pheripheral(POOL, pool)
        for vdp_no in range(vdp_config.get(UNITS_COUNT)):
            if vdp_config.get(ACC_TYPE) == 'STOCHASTIC':
                vdp = Stocastic_MRRVDP(ring_radius, pitch, vdp_type, vdp_config.get(
                    SUPPORTED_LAYER_LIST), vdp_config.get(BITRATE))
            else:
                vdp = MRRVDP(ring_radius, pitch, vdp_type,
                             vdp_config.get(SUPPORTED_LAYER_LIST), vdp_config.get(BITRATE))
            for vdp_element in range(vdp_config.get(ELEMENT_COUNT)):
                vdp_element = VDPElement(vdp_config[ELEMENT_SIZE], vdp_config.get(
                    RECONFIG), vdp_config.get(AUTO_RECONFIG), vdp_config.get(PRECISION))
                vdp.add_vdp_element(vdp_element)
            # * Need to call set vdp latency => includes latency of prop + tia latency + pd latency + etc
            vdp.set_vdp_latency()
            accelerator.add_vdp(vdp)
        accelerator.set_cache_size(vdp_config.get(ELEMENT_COUNT)*accelerator.cache_size_per_element)
    print("ACCELERATOR CREATED WITH THE GIVEN CONFIGURATION ")

    # # * Read Model file to load the dimensions of each layer
    nnModel = pd.read_csv(cnnModelDirectory+modelName)
    nnModel = nnModel.astype({"model_name": str, 'name': str, 'kernel_depth': int, 'kernel_height': int, 'kernel_width': int,	'tensor_count': int, 'input_shape': str,
                             'output_shape': str, 'tensor_shape': str,	'input_height': int,	'input_width': int, 'input_depth': int, 'output_height': int, 'output_width': int, 'output_depth': int})

    # # * filter specific layers for debugging
    # nnModel = nnModel.drop(nnModel[nnModel.name == "DepthWiseConv"].index)
    # nnModel = nnModel.drop(nnModel[nnModel.name == "Conv2D"].index)
    # nnModel = nnModel.drop(nnModel[nnModel.name == "PointWiseConv"].index)
    # nnModel = nnModel.drop(nnModel[nnModel.name == "Dense"].index)
    # nnModel = nnModel.drop(nnModel[nnModel.name == "MaxPooling2D"].index)

    accelerator.reset()
    total_latency = []
    vdp_ops = []
    vdp_sizes = []
    for idx in nnModel.index:
        accelerator.reset()
        layer_type = nnModel[LAYER_TYPE][idx]
        model_name = nnModel[MODEL_NAME][idx]
        kernel_depth = nnModel[KERNEL_DEPTH][idx]
        kernel_width = nnModel[KERNEL_WIDTH][idx]
        kernel_height = nnModel[KERNEL_HEIGHT][idx]
        tensor_count = nnModel[TENSOR_COUNT][idx]
        input_shape = nnModel[INPUT_SHAPE][idx]
        output_shape = nnModel[OUTPUT_SHAPE][idx]
        tensor_shape = nnModel[TENSOR_SHAPE][idx]
        input_height = nnModel[INPUT_HEIGHT][idx]
        input_width = nnModel[INPUT_WIDTH][idx]
        input_depth = nnModel[INPUT_DEPTH][idx]
        output_height = nnModel[OUTPUT_HEIGHT][idx]
        output_width = nnModel[OUTPUT_WIDTH][idx]
        output_depth = nnModel[OUTPUT_DEPTH][idx]
        # * debug statments to be deleted
        print('Layer Name  ;', layer_type)
        # print('Kernel Height', kernel_height,'Kernel width',kernel_width, 'Kernel Depth', kernel_depth)

        # * VDP size and Number of VDP operations per layer
        vdp_size = kernel_height*kernel_width*kernel_depth
        
        conv1 = np.random.randn(tensor_count,kernel_depth,kernel_height,kernel_width) 
        X = np.random.randn(1,input_depth,input_height,input_width)
        # print(X)
        stride = 1
        # Toeplitz matrix
        if layer_type == 'Conv2D' or layer_type == 'DepthWiseConv' or layer_type == 'PointWiseConv':
            X_im2col = im2col(X=X,conv1=conv1,pad=0,stride=1)
            toe_output_col = X_im2col.shape[1]
            # no_of_vdp_ops = output_height*output_depth*output_width
            no_of_vdp_ops = tensor_count*toe_output_col
        else:
            no_of_vdp_ops = output_height*output_depth*output_width
            toe_output_col = output_width
        
        
        
        # * Estimate the additional vdp operations to achieve the required precision in Analog Accelerators
        available_precision = accelerator.vdp_units_list[ZERO].vdp_element_list[ZERO].precision
        if available_precision < required_precision:
            required_precision_multiplier = math.ceil(
                required_precision/available_precision)
        else:
            required_precision_multiplier = 1
        no_of_vdp_ops = no_of_vdp_ops*required_precision_multiplier
         
        # * In Photonic VDPEs the weights are stationary and are operated using thermo optic tuning 
        # * When weights ae stationary the inputs are streamed in and a particular set of weights are used output height times output weight, the weights can be mapped frontal or lateral 
        
      
        
        # print('No Of VDP Ops', no_of_vdp_ops)
        # * Latency Calculation of the VDP operations
        layer_latency = 0
        # * Handles pooling layers and sends the requests to pooling unit
        if layer_type == 'MaxPooling2D':
            pooling_request = output_depth*output_height*output_width
            pool_latency = accelerator.pheripherals[POOL].get_request_latency(
                pooling_request)
            layer_latency = pool_latency
        else:
            # * other layers are handled here
            # * if VDP_type = MAM then the inputs are shared so need to process tensor by tensor rather than whole layer VDP operations
            # if accelerator.vdp_type == "MAM":
            if True:
                # print("MAM type architecture ")
                # vdp_per_tensor = int(no_of_vdp_ops/tensor_count)
                
                
                # print("Total tensor_count Ops ", tensor_count)
                # print("VDP per Tensor ", vdp_per_tensor)
                # print("Tensor Count ", tensor_count)
                for tensor in range(0, tensor_count):
                    layer_latency += controller.get_convolution_latency(accelerator, no_of_vdp_ops, vdp_size,toe_output_col)
                    # print('Tensor', tensor)
                    accelerator.reset()
                    # print("Layer latency", layer_latency)
            else:
                layer_latency = controller.get_convolution_latency(
                    accelerator, no_of_vdp_ops, vdp_size)
            # print('Layer Latency ',layer_latency)
            if layer_latency == 0:
                layer_latency = accelerator.vdp_units_list[ZERO].latency
        total_latency.append(layer_latency)
        vdp_ops.append(no_of_vdp_ops)
        vdp_sizes.append(vdp_size)
        
    # print("No od VDPs", vdp_ops)
    # print("VDP size", vdp_sizes)
    # print("Latency  =",total_latency)
    total_latency = sum(total_latency)
    hardware_utilization = metrics.get_hardware_utilization(
        controller.utilized_rings, controller.idle_rings)
    dynamic_energy_w = metrics.get_dynamic_energy(
        accelerator, controller.utilized_rings)
    static_power_w = metrics.get_static_power(accelerator)
    fps = (1/total_latency)
    power = (dynamic_energy_w/total_latency)+static_power_w
    fps_per_w = fps/power
    area = 0
    cache_writes = accelerator.cache_writes
    cache_reads = accelerator.cache_reads
    psum_writes = accelerator.psum_writes
    psum_reads = accelerator.psum_reads
    total_reads = cache_reads+psum_reads
    total_writes = cache_writes+psum_writes
    total_access = total_reads+total_writes+psum_reads+psum_writes
    # print("Psums Accumulations", accelerator.psum_writes)

    for accelearator_config in run_config:
        # * Set the values of ADC and DAC area and power values based on the Bit rate
        if accelearator_config[ACC_TYPE] == 'STOCHASTIC' or accelearator_config[ACC_TYPE] == 'ANALOG':
            running_br = accelearator_config[BITRATE]
            metrics.adc.area = adc_area_power[running_br][AREA]
            metrics.adc.power = adc_area_power[running_br][POWER]
            metrics.dac.area = dac_area_power[running_br][AREA]
            metrics.dac.power = dac_area_power[running_br][POWER]
        else:
            running_br = accelearator_config[BITRATE]
            # running_br = round(running_br, 2)
            metrics.adc.area = adc_area_power[round(running_br/PCA_ACC_Count,3)][AREA]
            metrics.adc.power = adc_area_power[round(running_br/PCA_ACC_Count,3)][POWER]
            metrics.dac.area = dac_area_power[round(running_br/PCA_ACC_Count,3)][AREA]
            metrics.dac.power = dac_area_power[round(running_br/PCA_ACC_Count,3)][POWER]
        # get_total_area(TYPE, X, Y, N, M, N_FC, M_FC):
        area += metrics.get_total_area(vdp_type, accelearator_config[UNITS_COUNT], accelearator_config[ELEMENT_SIZE],
                                       accelearator_config[ELEMENT_COUNT], accelearator_config[RECONFIG],accelearator_config[ACC_TYPE])
        # print("Area_pre", area)
    fps_per_w_area = fps_per_w/area
    # print("Area :", area)
    print("Total Latency ->", total_latency)
    print("FPS ->", fps)
    print("FPS/W  ->", fps_per_w)
    print("FPS/W/Area  ->", fps_per_w_area)
    print("Cache Writes", cache_writes)
    print("Cache Reads", cache_reads)
    print("Psum Writes", psum_writes)
    print("Psum Reads", psum_reads)
    print("Total Reads", total_reads)
    print("Total Writes", total_writes)
    
    result[NAME] = accelerator_config[0][NAME]
    result['Model_Name'] = modelName.replace(".csv", "")
    result[CONFIG] = run_config
    result[HARDWARE_UTILIZATION] = hardware_utilization
    result[TOTAL_LATENCY] = total_latency
    result[FPS] = fps
    result[TOTAL_DYNAMIC_ENERGY] = dynamic_energy_w
    result[TOTAL_STATIC_POWER] = static_power_w
    result[FPS_PER_W] = fps_per_w
    result[AREA] = area
    print("Area", area)
    result[FPS_PER_W_PER_AREA] = fps_per_w_area
    result["Total_Cache_Reads"] = total_reads
    result["Total_Cache_Writes"] = total_writes
    result["Total_Cache_Access"] = total_access
    result["Dataflow"] = "Output-Stationary"
    return result

  # * Creating accelerator with the configurations


accelerator_required_precision = 4
Architecture = 'MAM'
ACCELERATOR = [{ELEMENT_SIZE: 44 , ELEMENT_COUNT:  44, UNITS_COUNT: 20, RECONFIG: [
], VDP_TYPE:Architecture, NAME:Architecture, ACC_TYPE:'ANALOG', PRECISION:4, BITRATE: 1}]
# ANALOG_MAM_ACCELERATOR = [{ELEMENT_SIZE: 44, ELEMENT_COUNT: 44, UNITS_COUNT: 3172, RECONFIG: [
# ], VDP_TYPE:'MAM', NAME:'ANALOG_MAM', ACC_TYPE:'ANALOG', PRECISION:4, BITRATE: 5}]
# LIGHTBULB_ACCELERATOR = [{ELEMENT_SIZE: 16, ELEMENT_COUNT: 4, UNITS_COUNT: 1562, RECONFIG: [
# ], VDP_TYPE:'AMM', NAME:'LIGHTBULB', ACC_TYPE:'ANALOG', PRECISION:1, BITRATE: 50}]


tpc_list = [ACCELERATOR]
print("Required Precision ", accelerator_required_precision)
cnnModelDirectory = "./CNNModels/"
modelList = [f for f in listdir(
    cnnModelDirectory) if isfile(join(cnnModelDirectory, f))]
modelList = ['GoogLeNet.csv','ResNet50.csv','ShuffleNet_V2.csv', 'MobileNet_V2.csv']
system_level_results = []
for tpc in tpc_list:
    for modelName in modelList:
        print("Model being Processed ", modelName)
        system_level_results.append(
            run(modelName, cnnModelDirectory, tpc, accelerator_required_precision))
sys_level_results_df = pd.DataFrame(system_level_results)
sys_level_results_df.to_csv('Result/GLSVLSI/'+Architecture+'_WS_WITHOUT_PCA.csv')


# #* set clock increment time as the vdp latency time for uniform vdp accelerator
# clock_increment = accelerator.vdp_units_list[ZERO].latency

# #* For Hybrid accelerator the clock increment is the difference between the largest vdp latency and the smallest vdp latency
# #* vdp elements are sorted based on the element size during setup latency call

# # todo 1: Fix the logging part 2: Add visualization code   2. Add pooling layer energy calculation
# # todo 7. Add thermal tunning lateny to total latency

# * FPS -  18747656.542931136 
# Cycle 3276
# Clock 6.676000000000237e-08
# Clock Increment 2e-11
# Clock 6.676000000000237e-08
# Layer Latency  6.676000000000237e-08
