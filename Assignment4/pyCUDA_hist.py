#!/usr/bin/env python
import time
import argparse
from tabulate import tabulate

from pycuda import driver, compiler, gpuarray, tools
import pycuda.autoinit

import numpy as np
import scipy.signal
np.set_printoptions(suppress=True)
np.set_printoptions(linewidth=100)
import string
import random
import os

import matplotlib as mpl
mpl.use('agg')
import matplotlib.pyplot as plt

import pdb

def histOpt(histogramValues):
    """
    Generate histogram with opt kernel
        -> tiling
        -> shared memory histogram
        -> reduction
        -> coalesced memory access through warp multiple block size
    Input:
        variable histogramValues: 1-d array with values for histogram
    Return/Output: [hist, runtime]
    """

    #Setup CUDA
    #CUDA Kernel
    #Optimized histogram
    kernel_code = """
    #include <stdio.h>
    #define BINS {}

    __global__ void histOpt(unsigned short* histInput, int* histOutput) {{

        __shared__ int localHist[BINS];

        int bx = blockIdx.x;
        int tx = threadIdx.x;
        int x = bx * blockDim.x + tx;

        //Initialize bins to 0
        if (tx < BINS) {{
            localHist[tx] = 0;
        }}
        __syncthreads();

        //Calculate local
        int loc = (int) (histInput[x]/10);
        //printf("histInput[%d] = %d, Bin = %d\\n", x, histInput[x], loc);
        atomicAdd( &(localHist[loc]), 1);
        __syncthreads();

        //Store to global
        if (tx < BINS) {{
            //printf("Thread: %d, histOutput[%d] = %d, localHist[tx] = %d\\n", x, tx, histOutput[tx], localHist[tx]);
            atomicAdd( &(histOutput[tx]), localHist[tx] );
            //printf("Thread: %d, histOutput[%d] = %d, localHist[tx] = %d\\n", x, tx, histOutput[tx], localHist[tx]);
        }}

    }}
    """

    # Pre-calculate values used across all threads
    histogramValues_row_size = histogramValues.shape[0]
    histogramValues_col_size = histogramValues.shape[1]

    BLOCK_SIZE = 128

    # update template with current runtime requirements
    kernel = kernel_code.format(18)

    # Compile kernel
    # Set constant var
    compiled   = compiler.SourceModule(kernel)

    #Get compiled kernel
    func = compiled.get_function("histOpt")

    #Set up loop data
    base = np.power(2, 10).astype(np.int32)
    side = int(data.shape[0] / base)
    binCount = side**2
    histResult = np.zeros((binCount, 18))
    histResult = histResult.reshape(-1).astype(np.int32)

    # Iterate over each 1024x1024 dataset
    start = time.time()
    for i in range(side):
        for j in range(side):

            #Move data to device
            histogramValues_int = np.array(histogramValues[i*base:(i+1)*base, j*base:(j+1)*base]).astype(np.uint16)
            histogram_gpu = gpuarray.to_gpu(histogramValues_int)
            hist = gpuarray.zeros((18), np.int32)

            # Launch kernel
            func(histogram_gpu, hist, block = (BLOCK_SIZE,1,1), grid=(1024/BLOCK_SIZE*1024,1,1))

            # Save output
            bin_idx = i * side + j
            histResult[bin_idx*18:bin_idx*18+18] = hist.get()
            # print("Got to end of iter %d\nhistResult:\n%s" % (j,histResult[bin_idx:bin_idx+18] ))
    runtime = time.time()-start

    # test_result, __tmp = python_histOpt(matrix, filterVec, dDim)
    # print('CUDA_histOpt %d x %d time:  %.2E' % (histogramValues.shape[0], histogramValues.shape[1], runtime))
    # print('CUDA_histOpt==goldenDConv: %s' % np.allclose(convolvedResult, test_result))
    # # print('golden histOpt:\n %s' % test_result)
    # # print('CUDA histOpt val:\n %s' % convolvedResult)
    # if not(np.allclose(convolvedResult, test_result)):
    #     # print('Original Matrix:\n %s' % matrix)
    #     print('golden opt2 convolve:\n %s' % test_result)
    #     convolvedResult[(convolvedResult>0) & (convolvedResult<1)] = -1
    #     print('CUDA opt2 convolve val:\n %s' % convolvedResult)
    #     print('CUDA opt2 convolve:\n %s' % np.isclose(convolvedResult,test_result))
    # # print('--------------------')

    return [histResult, runtime]

def histNaive(histogramValues):
    """
    Generate histogram with naive kernel
        -> no shared memory histogram
        -> no reduction
    Input:
        variable histogramValues: 1-d array with values for histogram
    Return/Output: [hist, runtime]
    """

    #Setup CUDA
    #CUDA Kernel
    #Naive histogram
    kernel_code = """
    #include <stdio.h>
    #define BINS {}

    __global__ void histNaive(unsigned short* histInput, int* histOutput) {{

        int bx = blockIdx.x;
        int tx = threadIdx.x;
        int x = bx * blockDim.x + tx;

        //Calculate location
        int loc = (int) (histInput[x]/10);

        //Store to global
        atomicAdd( &(histOutput[loc]), 1 );

    }}
    """

    # Pre-calculate values used across all threads
    histogramValues_row_size = histogramValues.shape[0]
    histogramValues_col_size = histogramValues.shape[1]

    BLOCK_SIZE = 2

    # update template with current runtime requirements
    kernel = kernel_code.format(18)

    # Compile kernel
    # Set constant var
    compiled   = compiler.SourceModule(kernel)

    #Get compiled kernel
    func = compiled.get_function("histNaive")

    #Setup loop data
    base = np.power(2, 10).astype(np.int32)
    side = int(data.shape[0] / base)
    binCount = side**2
    histResult = np.zeros((binCount, 18))
    histResult = histResult.reshape(-1).astype(np.int32)

    # Iterate over each 1024x1024 dataset
    start = time.time()
    for i in range(side):
        for j in range(side):

            #Move data to device
            histogramValues_int = np.array(histogramValues[i*base:(i+1)*base, j*base:(j+1)*base]).astype(np.uint16)
            histogram_gpu = gpuarray.to_gpu(histogramValues_int)
            hist = gpuarray.zeros((18), np.int32)

            # Launch kernel
            func(histogram_gpu, hist, block = (BLOCK_SIZE,1,1), grid=(1024/BLOCK_SIZE*1024,1,1))

            # Save output
            bin_idx = i * side + j
            histResult[bin_idx*18:bin_idx*18+18] = hist.get()
            # print("Got to end of iter %d\nhistResult:\n%s" % (j,histResult[bin_idx:bin_idx+18] ))
    runtime = time.time()-start

    # test_result, __tmp = python_histOpt(matrix, filterVec, dDim)
    # print('CUDA_histNaive %d x %d time:  %.2E' % (histogramValues.shape[0], histogramValues.shape[1], runtime))
    return [histResult, runtime]

# Provided functions
def CustomPrintTime(py_time, naive_time, opt_time):
    ## Print running time for cpu, naive and optimized algorithms
    ## Arguments: Each argument is a list of length 3 that contains the running times for three cases

    if len(py_time) != len(naive_time) or len(py_time) != len(opt_time) or len(py_time) != 3:
        raise Exception('All lists should be 3, but get {}, {}, {}'.format(len(py_time), len(naive_time), len(opt_time)))
    headers = ['small_image', 'medium_image', 'large_image']
    py_time = ['Py'] + py_time
    naive_time = ['Naive'] + naive_time
    opt_time = ['Opt'] + opt_time
    table = [py_time, naive_time, opt_time]
    print "Time Taken by Kernels:"
    print tabulate(table, headers, tablefmt='fancy_grid').encode('utf-8')
def CustomPrintHistogram(histogram):
    ## Print the histogram
    ## Argument: a list of length 18 in which each element i represents the number of elements fall into the bin i.

    if len(histogram) != 18:
        raise Exception('length of the histogram must be 18, but get{}'.format(len(histogram)))
    header = ["{}".format(i) for i in range(18)]
    table = [histogram]
    print 'Histogram:'
    print tabulate(table, header, tablefmt='fancy_grid').encode('utf-8')
def CustomPrintSpeedUp(naive_kernel, opt_kernel):
    ## Print the speed up
    ## Arguments: The first argument is the naive kernel running time and the second is optimized version
    ## Each argument is the length of 3.

    if len(opt_kernel) != len(naive_kernel) or len(opt_kernel) != 3:
        raise Exception('lenght of naive_kernel and opt_kernel must be 3, but get {}, {}'.format(len(naive_kernel), len(opt_kernel)))
    speedup = [[s * 1.0/t for s, t in zip(naive_kernel, opt_kernel)]]
    print "Speedup(Naive/Optimized):"
    header = ['small_image', 'medium_image', 'large_image']
    print tabulate(speedup, header, tablefmt='fancy_grid').encode('utf-8')
def getData(path, mode):
    ## Get the input data
    ## Path: The path from which we extract data
    ## mode: size of teh data returned. 0 for first 2^20, 1 for 2^26 and 2 for full data

    data = np.memmap(path, dtype=np.uint16, mode='r')
    data = data.reshape(2**15, 2**15)
    if mode == 0:
        return data[:2**10, :2**10]
    if mode == 1:
        return data[:2**13, :2**13]
    if mode == 2:
        return data
    raise Exception('mode must be one of 0, 1, 2, but get {}'.format(mode))
def CustomHistEqual(py, naive, opt):
    ## Check the equality of the histograms
    ## Arguments: each argument is a list containing same amount of bins

    if len(py) != len(naive) or len(py) != len(opt):
        raise Exception('All length must be equal, but get {}, {}, {}'.format(len(py), len(naive), len(opt)))
    py_naive = True
    py_opt = True
    if not np.all(py == naive):
        print "Python != Naive"
        py_naive = False
    if not np.all(py == opt):
        print "Python != Opt"
        py_opt = False
    if py_naive and py_opt:
        print "All the histograms are equal!!"
def histogram(data, exponent = 10):
    ## Calculate the histogram
    ## data: A 2-D numpy array
    ## exponent: exponent of two. The sub-region size is 2^exponet by 2^exponent
    ## This function outputs a 1D array rather than a list. You must transform it to a list before you
    ## call CustomPrintFunction

    base = np.power(2, exponent).astype(np.int32)
    side = int(data.shape[0] / base)
    num_bins = side**2
    bins = np.zeros((num_bins, 18))
    for i in range(side):
        for j in range(side):
            hist = np.histogram(data[i*base:(i+1)*base, j*base:(j+1)*base], np.arange(0, 181, 10))
            bin_idx = i * side + j
            bins[bin_idx,:] = hist[0]
    bins = bins.reshape(-1)
    return bins

if __name__=="__main__":

    #initialize arrays
    cpu_array = []
    cpu_Runtime_array = []

    gpu_Naive_array = []
    gpu_NaiveRuntime_array = []

    gpu_Opt_array = []
    gpu_OptRuntime_array = []

    dimSize = [18,1152,18432]
    # 2^10x2^10 input
    print("Working on 2^10 x 2^10 input:\n")
    if 1==1:
        data = getData("/opt/data/hist_data.dat", mode=0)

        start = time.time()
        cpuData = histogram(data, exponent = 10)
        cpuTime = time.time() - start
        cpu_Runtime_array.append(cpuTime)
        print('CPU_hist %d x %d time:  %.2E' % (data.shape[0], data.shape[1], cpuTime))

        histNaiveData, histNaiveRuntime = histNaive(data)
        gpu_Naive_array.append(histNaiveData)
        gpu_NaiveRuntime_array.append(histNaiveRuntime)

        histOptData, histOptRuntime = histOpt(data)
        gpu_Opt_array.append(histOptData)
        gpu_OptRuntime_array.append(histOptRuntime)

        CustomHistEqual(cpuData, histNaiveData, histOptData)
        CustomPrintHistogram(histNaiveData)
        CustomPrintHistogram(histOptData)
    print("------------------------------------------------------")

    # 2^13x2^13 input
    print("Working on 2^13 x 2^13 input:\n")
    if 1==1:
        data = getData("/opt/data/hist_data.dat", mode=1)

        start = time.time()
        cpuData = histogram(data, exponent = 10)
        cpuTime = time.time() - start
        cpu_Runtime_array.append(cpuTime)
        print('CPU_hist %d x %d time:  %.2E' % (data.shape[0], data.shape[1], cpuTime))

        histNaiveData, histNaiveRuntime = histNaive(data)
        gpu_Naive_array.append(histNaiveData)
        gpu_NaiveRuntime_array.append(histNaiveRuntime)

        histOptData, histOptRuntime = histOpt(data)
        gpu_Opt_array.append(histOptData)
        gpu_OptRuntime_array.append(histOptRuntime)

        CustomHistEqual(cpuData, histNaiveData, histOptData)
        CustomPrintHistogram(histNaiveData[0:18])
        CustomPrintHistogram(histNaiveData[-18:])
        CustomPrintHistogram(histOptData[0:18])
        CustomPrintHistogram(histOptData[-18:])
    print("------------------------------------------------------")

    # 2^10x2^10 input
    print("Working on 2^15 x 2^15 input:\n")
    if 1==1:
        data = getData("/opt/data/hist_data.dat", mode=2)

        start = time.time()
        cpuData = histogram(data, exponent = 10)
        cpuTime = time.time() - start
        cpu_Runtime_array.append(cpuTime)
        print('CPU_hist %d x %d time:  %.2E' % (data.shape[0], data.shape[1], cpuTime))

        histNaiveData, histNaiveRuntime = histNaive(data)
        gpu_Naive_array.append(histNaiveData)
        gpu_NaiveRuntime_array.append(histNaiveRuntime)

        histOptData, histOptRuntime = histOpt(data)
        gpu_Opt_array.append(histOptData)
        gpu_OptRuntime_array.append(histOptRuntime)

        CustomHistEqual(cpuData, histNaiveData, histOptData)
        CustomPrintHistogram(histNaiveData[0:18])
        CustomPrintHistogram(histNaiveData[-18:])
        CustomPrintHistogram(histOptData[0:18])
        CustomPrintHistogram(histOptData[-18:])
    print("------------------------------------------------------")

    CustomPrintTime(cpu_Runtime_array, gpu_NaiveRuntime_array, gpu_OptRuntime_array)
    CustomPrintSpeedUp(gpu_NaiveRuntime_array, gpu_OptRuntime_array)

    # Plot
    plt.gcf()
    plt.plot(dimSize[0], cpu_Runtime_array[0], marker='o', markersize=3, color='red', label="CPU")
    plt.plot(dimSize, gpu_NaiveRuntime_array, 'b', label="GPU_Naive")
    plt.plot(dimSize, gpu_OptRuntime_array, 'g', label="GPU_Opt")
    plt.legend(loc='best')
    plt.xlabel('TotalBins')
    plt.ylabel('RunTime (s)')
    plt.title("pythonCPU RunTime vs CUDA GPU RunTime")
    plt.gca().set_xlim((min(dimSize), max(dimSize)))
    plt.gca().set_ylim([0,max(max(cpu_Runtime_array),max(gpu_NaiveRuntime_array),max(gpu_OptRuntime_array))])
    plt.autoscale()
    plt.tight_layout()
    plt.ticklabel_format(axis='y',style='sci')
    # ax.yaxis.set_major_formatter(mpl.ticker.FormatStrFormatter('%.2e'))
    plt.savefig('pythonCPU_gpuCUDA_bins_plot.png',bbox_inches='tight')
    plt.close()

    # Test CPU dilation
    if 1==0:
        for dDim in range(1,4):
            tmp = np.random.randint(0,high=100,size=(10*dDim,15*dDim))

            print("Input:\n%s\n" % tmp)
            # filterVec = np.random.randint(5,size=9)
            filterVec = np.random.randint(9,size=9)
            # filterVec = [4, 0, 2, 0, 2, 2, 2, 2, 4]
            print("dConv:\n%s\n" % filterVec)

            vOutput,vTime = python_histOpt_verify(tmp,filterVec,dDim)
            dOutput,dTime = python_histOpt(tmp,filterVec,dDim)
            print('verifyOutput==cpuDconvOutput: %s' % np.allclose(vOutput, dOutput))
            print('dilatedConv:\n%s\n' % dOutput)
            print('verifyConv:\n%s\n' % vOutput)
            print('cpuDilatedConvRunTime: %.2E, cpuCorrelationConvRunTime: %.2E' %(dTime, vTime))
            print("-----------------------------")

    if 1==0:
        filterVec = np.random.randint(100,size=9)
        dDim = np.random.randint(1,high=3,size=1)[0]
        # tmp = np.zeros([ydim, xdim])
        # for i in range(tmp.shape[0]):
        #     for j in range(tmp.shape[1]):
        #         tmp[i,j] = i*tmp.shape[1]+j

        tmp = np.random.randint(0,high=100,size=(100,200))
        print("Input [%d, %d]:\n%s\n" % (ydim, xdim, tmp))
        print("kernel (%d):\n%s\n" % (dDim,filterVec))
        histOpt(tmp, filterVec, dDim)

    # Vary dilation factor
    if 1==0:
        dimSize = []
        for i in range(1,101):
            filterVec = np.random.randint(100,size=9)
            dDim = i
            # tmp = np.zeros([ydim, xdim])
            # for i in range(tmp.shape[0]):
            #     for j in range(tmp.shape[1]):
            #         tmp[i,j] = i*tmp.shape[1]+j

            tmp = np.random.randint(0,high=100,size=(100,200))
            # print("kernel (stride %d):\n%s\n" % (dDim,filterVec))

            gpuConvolved, gpuRuntime = histOpt(tmp, filterVec, dDim)
            gpu_histOptRuntime_array_dDim.append(gpuRuntime)

            cpuConvolved, cpuRuntime = python_histOpt(tmp, filterVec, dDim)
            cpu_histOptRuntime_array_dDim.append(cpuRuntime)

            dimSize.append(i)
            if i<4:
                print("Input [%d, %d] with dilation %d:\n%s\n" % (ydim, xdim, i, tmp))
                print("GPU Output:\n%s\n" % gpuConvolved)
                print("CPU Output:\n%s\n" % cpuConvolved)

            print('[%d, %d, dilation=%d] -> CUDA_histOpt==cpuDConv: %s' % (ydim, xdim, dDim, np.allclose(gpuConvolved, cpuConvolved)))
            print('CUDA_runtime: %.2E, CPU_runtime: %.2E\n' %(gpuRuntime, cpuRuntime))
            print("-----------------------------")

        # Plot
        plt.gcf()
        plt.plot(dimSize, cpu_histOptRuntime_array_dDim, 'r', label="CPU")
        plt.plot(dimSize, gpu_histOptRuntime_array_dDim, 'b', label="GPU")
        plt.legend(loc='best')
        plt.xlabel('Dilation Dim')
        plt.ylabel('RunTime (s)')
        plt.title("pythonCPU RunTime vs CUDA GPU RunTime (Dilation Factor)")
        plt.gca().set_xlim((min(dimSize), max(dimSize)))
        plt.gca().set_ylim([0,max(cpu_histOptRuntime_array_dDim)])
        plt.autoscale()
        plt.tight_layout()
        plt.ticklabel_format(axis='y',style='sci')
        # ax.yaxis.set_major_formatter(mpl.ticker.FormatStrFormatter('%.2e'))
        plt.savefig('pythonCPU_dDim_gpuCUDA_plot.png',bbox_inches='tight')
        plt.close()

    # Vary matrix size
    if 1==0:
        dimSize = []
        for i in range(1,11):
            x = 25*i
            y = 35*i
            filterVec = np.random.randint(100,size=9)
            dDim = 2
            # tmp = np.zeros([ydim, xdim])
            # for i in range(tmp.shape[0]):
            #     for j in range(tmp.shape[1]):
            #         tmp[i,j] = i*tmp.shape[1]+j

            tmp = np.random.randint(0,high=100,size=(x,y))
            # print("Input [%d, %d]:\n%s\n" % (x, y, tmp))
            # print("kernel (stride %d):\n%s\n" % (dDim,filterVec))

            gpuConvolved, gpuRuntime = histOpt(tmp, filterVec, dDim)
            gpu_histOptRuntime_array_matSize.append(gpuRuntime)

            cpuConvolved, cpuRuntime = python_histOpt(tmp, filterVec, dDim)
            cpu_histOptRuntime_array_matSize.append(cpuRuntime)

            dimSize.append(25*i*35*i)
            if i<4:
                print("Input [%d, %d] with dilation %d:\n%s\n" % (y, x, dDim, tmp))
                print("GPU Output:\n%s\n" % gpuConvolved)
                print("CPU Output:\n%s\n" % cpuConvolved)

            print('[%d, %d] -> CUDA_histOpt==cpuDConv: %s' % (y, x, np.allclose(gpuConvolved, cpuConvolved)))
            print('CUDA_runtime: %.2E, CPU_runtime: %.2E\n' %(gpuRuntime, cpuRuntime))
            print("-----------------------------")

        # Plot
        plt.gcf()
        plt.plot(dimSize, cpu_histOptRuntime_array_matSize, 'r', label="CPU")
        plt.plot(dimSize, gpu_histOptRuntime_array_matSize, 'b', label="GPU")
        plt.legend(loc='best')
        plt.xlabel('Matrix Size')
        plt.ylabel('RunTime (s)')
        plt.title("pythonCPU RunTime vs CUDA GPU RunTime (Matrix Size)")
        plt.gca().set_xlim((min(dimSize), max(dimSize)))
        plt.gca().set_ylim([0,max(cpu_histOptRuntime_array_matSize)])
        plt.autoscale()
        plt.tight_layout()
        plt.ticklabel_format(axis='y',style='sci')
        # ax.yaxis.set_major_formatter(mpl.ticker.FormatStrFormatter('%.2e'))
        plt.savefig('pythonCPU_matSize_gpuCUDA_plot.png',bbox_inches='tight')
        plt.close()

    # Vary filter size
    if 1==0:
        dimSize = []
        for i in range(3,13):
            filterVec = np.random.randint(100,size=i*i)
            dDim = 3
            # tmp = np.zeros([ydim, xdim])
            # for i in range(tmp.shape[0]):
            #     for j in range(tmp.shape[1]):
            #         tmp[i,j] = i*tmp.shape[1]+j

            tmp = np.random.randint(0,high=100,size=(ydim,xdim))
            # print("Input [%d, %d]:\n%s\n" % (ydim, xdim, tmp))
            # print("kernel (stride %d):\n%s\n" % (dDim,filterVec))

            gpuConvolved, gpuRuntime = histOpt(tmp, filterVec, dDim)
            gpu_histOptRuntime_array_filterSize.append(gpuRuntime)

            cpuConvolved, cpuRuntime = python_histOpt(tmp, filterVec, dDim)
            cpu_histOptRuntime_array_filterSize.append(cpuRuntime)

            dimSize.append(i)
            if i<6:
                print("Input [%d, %d] with dilation %d and kernelSize:[%d,%d]\n%s\n" % (ydim, xdim, dDim, i, i, tmp))
                print("GPU Output:\n%s\n" % gpuConvolved)
                print("CPU Output:\n%s\n" % cpuConvolved)

            print('[%d, %d, kernelSize:[%d,%d]] -> CUDA_histOpt==cpuDConv: %s' % (ydim, xdim, i, i, np.allclose(gpuConvolved, cpuConvolved)))
            print('CUDA_runtime: %.2E, CPU_runtime: %.2E\n' %(gpuRuntime, cpuRuntime))
            print("-----------------------------")

        # Plot
        plt.gcf()
        plt.plot(dimSize, cpu_histOptRuntime_array_filterSize, 'r', label="CPU")
        plt.plot(dimSize, gpu_histOptRuntime_array_filterSize, 'b', label="GPU")
        plt.legend(loc='best')
        plt.xlabel('Mask Dim')
        plt.ylabel('RunTime (s)')
        plt.title("pythonCPU RunTime vs CUDA GPU RunTime (Mask Size)")
        plt.gca().set_xlim((min(dimSize), max(dimSize)))
        plt.gca().set_ylim([0,max(cpu_histOptRuntime_array_filterSize)])
        plt.autoscale()
        plt.tight_layout()
        plt.ticklabel_format(axis='y',style='sci')
        # ax.yaxis.set_major_formatter(mpl.ticker.FormatStrFormatter('%.2e'))
        plt.savefig('pythonCPU_maskSize_gpuCUDA_plot.png',bbox_inches='tight')
