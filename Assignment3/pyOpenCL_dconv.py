import time
import argparse

import pyopencl as cl
import pyopencl.array

import numpy as np
import os
os.environ['PYOPENCL_COMPILER_OUTPUT'] = '1'

import matplotlib as mpl
mpl.use('agg')
import matplotlib.pyplot as plt

import pdb

def setup_CL():
    """
    Sets up openCL platform devices,
        context, and CommandQueue

    Returns: list of device, context, CommandQueue
    """

    #Set up openCL platform
    NAME = 'NVIDIA CUDA'
    platforms = cl.get_platforms()

    dev = None
    for p in platforms:
        #Easy switching for local vs remote machine
        if p.name == 'Apple':
            NAME = 'Apple'
        if p.name == NAME:
            dev = p.get_devices()

    # Command queue, enable GPU profiling
    ctx = cl.Context(dev)
    queue = cl.CommandQueue(ctx,properties=cl.command_queue_properties.PROFILING_ENABLE)

    return [dev,ctx,queue]

def dconv(matrix, filterVec, dDim):
    """
    Calculate dilated conv of a MxN matrix
    Measure runtime of overall calculation
    Input:
        variable matrix: JxK numpy 2-d array of integer values
        variable filterVec: Filter values
        variable dDim: dilation coefficient
    Return/Output: [convolvedResult, runtime]
    """

    #Setup openCL
    dev, ctx, queue = setup_CL()

    #openCL Kernel
    #Dilated Convolution
    kernel_code = """
    #define MATRIX_ROW_SIZE {}
    #define MATRIX_COL_SIZE {}
    #define TILE_WIDTH {}
    #define DDIM {}
    #define KDIM {}
    #define KDIM_EXP {}
    #define KDIM_OFFSET {}
    #define n {}

    __kernel void func(__global int* input, __global int* kernelVals, __global int* convolved) {{

        //__shared__ float M[MATRIX_ROW_SIZE][1];
        //__shared__ float N[TILE_WIDTH][TILE_WIDTH];

        int bx = get_group_id(0);  int by = get_group_id(1);
        int tx = get_local_id(0); int ty = get_local_id(1);
        int Row = by * get_local_size(1) + ty;
        int Col = bx * get_local_size(0) + tx;
        int Cvalue = 0;

        // Calculate dilated convolution value for each thread
        for (int t = 0; t < KDIM*KDIM;++t) {{

            if((Row - KDIM_OFFSET + (t/KDIM)*DDIM) >= 0 && (Row - KDIM_OFFSET + (t/KDIM)*DDIM) < MATRIX_ROW_SIZE &&
               (Col - KDIM_OFFSET + (t%KDIM)*DDIM) >= 0 && (Col - KDIM_OFFSET + (t%KDIM)*DDIM) < MATRIX_COL_SIZE)
            {{
                Cvalue += kernelVals[t] * input[(Row - KDIM_OFFSET) * MATRIX_COL_SIZE + Col - KDIM_OFFSET + (t/KDIM)*DDIM * MATRIX_COL_SIZE + (t%KDIM)*DDIM];
                //printf("A kernelVals[%d] = %d, input[%d] = %d, Row: %d, Col: %d\\n", t, kernelVals[t], ((Row - KDIM_OFFSET) * MATRIX_COL_SIZE + Col - KDIM_OFFSET + (t/KDIM)*DDIM * MATRIX_COL_SIZE + (t%KDIM)*DDIM), input[((Row - KDIM_OFFSET) * MATRIX_COL_SIZE + Col - KDIM_OFFSET + (t/KDIM)*DDIM * MATRIX_COL_SIZE + (t%KDIM)*DDIM)], Row, Col);
            }}
        }}

        barrier(CLK_LOCAL_MEM_FENCE);

        //Assign values to output
        if(Row<MATRIX_ROW_SIZE && Col < MATRIX_COL_SIZE) {{
            convolved[Row*MATRIX_COL_SIZE + Col] = Cvalue;
            //printf("Cvalue = %d, loc = %d, Row: %d, Col: %d\\n", Cvalue, (Row*MATRIX_COL_SIZE + Col), Row, Col);
        }}
    }}
    """

    #Move data to device
    matrix_int = matrix.astype(np.int32)
    matrix_gpu = cl.array.to_device(queue, matrix_int)
    filterVec_int = filterVec.astype(np.int32)
    filterVec_gpu = cl.array.to_device(queue, filterVec_int)
    convolved = cl.array.empty(queue, (matrix.shape[0], matrix.shape[1]), np.int32)

    # Pre-calculate values used across all threads
    matrix_row_size = matrix.shape[0]
    matrix_col_size = matrix.shape[1]

    kernelExpandedDim = int((dDim-1)*(np.sqrt(len(filterVec))-1)+np.sqrt(len(filterVec))) # Expanded Size
    dconv_offset = int(kernelExpandedDim/2) # value used to center input matrix on kernel

    TILE_WIDTH = 32

    #Calculate workItems, workGroup size, workGroups for input
    matrix_val_count = matrix_int.shape[0]*matrix_int.shape[1]
    xWorkItems = int(int(matrix_col_size-1)/TILE_WIDTH)+1
    yWorkItems = int(int(matrix_row_size-1)/TILE_WIDTH)+1
    totalWorkItems = float(TILE_WIDTH*TILE_WIDTH)
    groups = np.int(max(np.ceil(matrix_val_count / xWorkItems),1))

    # print("workItems: %s, matrix_val_count: %s, groups: %s" % (totalWorkItems, matrix_val_count, groups))

    # update template with current runtime requirements
    kernel = kernel_code.format(matrix_row_size, matrix_col_size, TILE_WIDTH, dDim, int(np.sqrt(len(filterVec))),kernelExpandedDim,dconv_offset,max(matrix_col_size, matrix_row_size))

    #Launch kernel and time it
    #Set global ID, workItems, workGroups
    prg = cl.Program(ctx, kernel).build()
    start = time.time()
    event = prg.func(queue, (xWorkItems*TILE_WIDTH,yWorkItems*TILE_WIDTH,1),(TILE_WIDTH,TILE_WIDTH,1), matrix_gpu.data, filterVec_gpu.data, convolved.data)
    runtime = time.time()-start

    #Save output
    convolvedResult = convolved.get()

    # print('openCL_opt2 %d x %d transpose-mult time:  %.2E' % (matrix.shape[0], matrix.shape[1], runtime))
    # print('openCL_opt2_transposed==goldenTransposed: %s' % np.allclose(transposed, np.transpose(matrix)))
    # print('openCL_opt2_mult==goldenMult: %s' % np.allclose(convolvedResult, matrix.dot(np.transpose(matrix))))
    # if not(np.allclose(convolvedResult, matrix.dot(np.transpose(matrix)))):
    #     # print('Original Matrix:\n %s' % matrix)
    #     print('openCL_opt2 transposed val:\n %s' % transposed)
    #     print('golden transpose-mult:\n %s' % matrix.dot(np.transpose(matrix)))
    #     convolvedResult[(convolvedResult>0) & (convolvedResult<1)] = -1
    #     print('openCL_opt2 mult val:\n %s' % convolvedResult)
    #     print('openCL_opt2 transpose-mult:\n %s' % np.isclose(convolvedResult,matrix.dot(np.transpose(matrix))))
    # print('--------------------')

    return [convolvedResult, runtime]

def python_dconv_verify(matrix, filterVec, dDim):
    """
    Verify dilated conv of a MxN matrix using correlation
    Measure runtime of overall calculation
    Input:
        variable matrix: JxK numpy 2-d array of integer values
        variable filterVec: Filter values
        variable dDim: dilation coefficient
    Return/Output: [convolved, runtime]
    """

    # Calculate expected corr matrix size and the indices that are nonzero
    correlationDim = int((dDim-1)*(np.sqrt(len(filterVec))-1)+np.sqrt(len(filterVec)))
    dconv_kernel = np.zeros([correlationDim,correlationDim])
    dconv_offset = int(correlationDim/2) # value used to center input matrix on kernel
    corrIdx = range(0,int(dDim*(np.sqrt(len(filterVec))-1)+1),dDim) # range of values that are nonzero

    # print("coreDim: %d, dconv_offset: %d, corrIdx: %s" % (correlationDim, dconv_offset, list(corrIdx)))

    # Copy all FilterVec values to correlation kernel
    vecIndex = 0
    for i in corrIdx:
        for j in corrIdx:
            dconv_kernel[i,j] = filterVec[vecIndex]
            vecIndex += 1

    # print(dconv_kernel)

    # Calculate convolution centered at each index
    # i,j are matrix input indices, k,m corr indices
    output = np.zeros([matrix.shape[0],matrix.shape[1]])
    start = time.time()
    for i in range(0,matrix.shape[0]):
        for j in range(0,matrix.shape[1]):
            sum = 0
            # Convolution dims
            # NOTE: The difference between this solution and the other is this iterates over every product
            # in an MxN matrix while the non-verify solution only iterates over the actual values of interest
            for k in range(0,correlationDim):
                for m in range(0,correlationDim):

                    # If out of bounds -> ignore that input
                    dconv_idx = np.array([k, m])
                    matrix_idx = np.array([i + k - dconv_offset,j + m - dconv_offset])

                    if (matrix_idx>=0).all() and matrix_idx[0]<matrix.shape[0] and matrix_idx[1]<matrix.shape[1]:
                        dconv = dconv_kernel[dconv_idx[0], dconv_idx[1]]
                        val = matrix[matrix_idx[0],matrix_idx[1]]
                        sum += dconv * val

            output[i,j] = sum
    end = time.time()-start
    return [output,end]

def python_dconv(matrix, filterVec, dDim):
    """
    Calculate dilated conv of a MxN matrix
    Measure runtime of overall calculation
    Input:
        variable matrix: JxK numpy 2-d array of integer values
        variable filterVec: Filter values
        variable dDim: dilation coefficient
    Return/Output: [convolved, runtime]
    """

    # Calculate indices that are nonzero
    correlationDim = int((dDim-1)*(np.sqrt(len(filterVec))-1)+np.sqrt(len(filterVec)))
    dconv_offset = int(correlationDim/2) # value used to center input matrix on kernel
    dIdx = range(0,int(dDim*(np.sqrt(len(filterVec))-1)+1),dDim) # range of values that are nonzero
    filterDim = int(np.sqrt(len(filterVec)))

    # print("coreDim: %d, dconv_offset: %d, corrIdx: %s" % (correlationDim, dconv_offset, list(dIdx)))

    output = np.zeros([matrix.shape[0],matrix.shape[1]])

    # Iterate over all indices by stride
    start = time.time()
    for i in range(0, matrix.shape[0]):
        for j in range(0, matrix.shape[1]):

            index_sum = 0
            filterIdx = 0

            # Calculate convolution for i,j index
            for k in dIdx:
                for m in dIdx:

                    # Offset based on dconv centering
                    matrix_idx = np.array([i + k - dconv_offset,j + m - dconv_offset])

                    # Only update sum if in bounds
                    # Offset matrix index
                    if (matrix_idx>=0).all() and matrix_idx[0]<matrix.shape[0] and matrix_idx[1]<matrix.shape[1]:
                        index_sum += filterVec[filterIdx] * matrix[matrix_idx[0],matrix_idx[1]]
                    filterIdx += 1

            output[i,j] = index_sum
    end = time.time()-start
    return [output, end]

if __name__=="__main__":
    # Starting dims
    ydim=100
    xdim=200

    #initialize arrays
    cpu_dconv_array = []
    cpu_dconvRuntime_array_dDim = []
    cpu_dconvRuntime_array_filterSize = []
    cpu_dconvRuntime_array_matSize = []

    gpu_dconv_array = []
    gpu_dconvRuntime_array = []

    gpu_dconv_dDim = []
    gpu_dconvRuntime_array_dDim = []

    gpu_filterSize = []
    gpu_dconvRuntime_array_filterSize = []

    gpu_matSize = []
    gpu_dconvRuntime_array_matSize = []


    # Test CPU dilation
    if 1==1:
        for dDim in range(1,4):
            tmp = np.random.randint(0,high=100,size=(10*dDim,15*dDim))

            print("Input:\n%s\n" % tmp)
            # filterVec = np.random.randint(5,size=9)
            filterVec = np.random.randint(9,size=9)
            # filterVec = [4, 0, 2, 0, 2, 2, 2, 2, 4]
            print("dConv:\n%s\n" % filterVec)

            vOutput,vTime = python_dconv_verify(tmp,filterVec,dDim)
            dOutput,dTime = python_dconv(tmp,filterVec,dDim)
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
        dconv(tmp, filterVec, dDim)

    # Vary dilation factor
    if 1==1:
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

            gpuConvolved, gpuRuntime = dconv(tmp, filterVec, dDim)
            gpu_dconvRuntime_array_dDim.append(gpuRuntime)

            cpuConvolved, cpuRuntime = python_dconv(tmp, filterVec, dDim)
            cpu_dconvRuntime_array_dDim.append(cpuRuntime)

            dimSize.append(i)
            if i<4:
                print("Input [%d, %d] with dilation %d:\n%s\n" % (ydim, xdim, i, tmp))
                print("GPU Output:\n%s\n" % gpuConvolved)
                print("CPU Output:\n%s\n" % cpuConvolved)

            print('[%d, %d, dilation=%d] -> OpenCL_dconv==cpuDConv: %s' % (ydim, xdim, dDim, np.allclose(gpuConvolved, cpuConvolved)))
            print('OpenCL_runtime: %.2E, CPU_runtime: %.2E\n' %(gpuRuntime, cpuRuntime))
            print("-----------------------------")

        # Plot
        plt.gcf()
        plt.plot(dimSize, cpu_dconvRuntime_array_dDim, 'r', label="CPU")
        plt.plot(dimSize, gpu_dconvRuntime_array_dDim, 'b', label="GPU")
        plt.legend(loc='best')
        plt.xlabel('Dilation Dim')
        plt.ylabel('RunTime (s)')
        plt.title("pythonCPU RunTime vs openCL GPU RunTime (Dilation Factor)")
        plt.gca().set_xlim((min(dimSize), max(dimSize)))
        plt.gca().set_ylim([0,max(cpu_dconvRuntime_array_dDim)])
        plt.autoscale()
        plt.tight_layout()
        plt.ticklabel_format(axis='y',style='sci')
        # ax.yaxis.set_major_formatter(mpl.ticker.FormatStrFormatter('%.2e'))
        plt.savefig('pythonCPU_dDim_gpuOpenCL_plot.png',bbox_inches='tight')
        plt.close()

    # Vary matrix size
    if 1==1:
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

            gpuConvolved, gpuRuntime = dconv(tmp, filterVec, dDim)
            gpu_dconvRuntime_array_matSize.append(gpuRuntime)

            cpuConvolved, cpuRuntime = python_dconv(tmp, filterVec, dDim)
            cpu_dconvRuntime_array_matSize.append(cpuRuntime)

            dimSize.append(25*i*35*i)
            if i<4:
                print("Input [%d, %d] with dilation %d:\n%s\n" % (y, x, dDim, tmp))
                print("GPU Output:\n%s\n" % gpuConvolved)
                print("CPU Output:\n%s\n" % cpuConvolved)

            print('[%d, %d] -> OpenCL_dconv==cpuDConv: %s' % (y, x, np.allclose(gpuConvolved, cpuConvolved)))
            print('OpenCL_runtime: %.2E, CPU_runtime: %.2E\n' %(gpuRuntime, cpuRuntime))
            print("-----------------------------")

        # Plot
        plt.gcf()
        plt.plot(dimSize, cpu_dconvRuntime_array_matSize, 'r', label="CPU")
        plt.plot(dimSize, gpu_dconvRuntime_array_matSize, 'b', label="GPU")
        plt.legend(loc='best')
        plt.xlabel('Matrix Size')
        plt.ylabel('RunTime (s)')
        plt.title("pythonCPU RunTime vs openCL GPU RunTime (Matrix Size)")
        plt.gca().set_xlim((min(dimSize), max(dimSize)))
        plt.gca().set_ylim([0,max(cpu_dconvRuntime_array_matSize)])
        plt.autoscale()
        plt.tight_layout()
        plt.ticklabel_format(axis='y',style='sci')
        # ax.yaxis.set_major_formatter(mpl.ticker.FormatStrFormatter('%.2e'))
        plt.savefig('pythonCPU_matSize_gpuOpenCL_plot.png',bbox_inches='tight')
        plt.close()

    # Vary filter size
    if 1==1:
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

            gpuConvolved, gpuRuntime = dconv(tmp, filterVec, dDim)
            gpu_dconvRuntime_array_filterSize.append(gpuRuntime)

            cpuConvolved, cpuRuntime = python_dconv(tmp, filterVec, dDim)
            cpu_dconvRuntime_array_filterSize.append(cpuRuntime)

            dimSize.append(i)
            if i<6:
                print("Input [%d, %d] with dilation %d and kernelSize:[%d,%d]\n%s\n" % (ydim, xdim, dDim, i, i, tmp))
                print("GPU Output:\n%s\n" % gpuConvolved)
                print("CPU Output:\n%s\n" % cpuConvolved)

            print('[%d, %d, kernelSize:[%d,%d]] -> OpenCL_dconv==cpuDConv: %s' % (ydim, xdim, i, i, np.allclose(gpuConvolved, cpuConvolved)))
            print('OpenCL_runtime: %.2E, CPU_runtime: %.2E\n' %(gpuRuntime, cpuRuntime))
            print("-----------------------------")

        # Plot
        plt.gcf()
        plt.plot(dimSize, cpu_dconvRuntime_array_filterSize, 'r', label="CPU")
        plt.plot(dimSize, gpu_dconvRuntime_array_filterSize, 'b', label="GPU")
        plt.legend(loc='best')
        plt.xlabel('Mask Dim')
        plt.ylabel('RunTime (s)')
        plt.title("pythonCPU RunTime vs openCL GPU RunTime (Mask Size)")
        plt.gca().set_xlim((min(dimSize), max(dimSize)))
        plt.gca().set_ylim([0,max(cpu_dconvRuntime_array_filterSize)])
        plt.autoscale()
        plt.tight_layout()
        plt.ticklabel_format(axis='y',style='sci')
        # ax.yaxis.set_major_formatter(mpl.ticker.FormatStrFormatter('%.2e'))
        plt.savefig('pythonCPU_maskSize_gpuOpenCL_plot.png',bbox_inches='tight')
