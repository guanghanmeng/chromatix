from chromatix.elements import ObjectivePointSource, PhaseMask, FFLens
from chromatix import Microscope, OpticalSystem
from chromatix.utils import trainable
from chromatix.functional.phase_masks import flat_phase
import jax
import jax.numpy as jnp
import numpy as np
from flax import linen as nn
from functools import partial
from time import perf_counter_ns

num_devices = 4
num_planes_per_device = 32
num_planes = num_devices * num_planes_per_device
shape = (1536, 1536)  # number of pixels in simulated field
spacing = 0.3  # spacing of pixels for the final PSF, microns
spectrum = 0.532  # microns
spectral_density = 1.0
f = 100.0  # focal length, microns
n = 1.33  # refractive index of medium
NA = 0.8  # numerical aperture of objective

microscope = Microscope(
    optical_system=[
        ObjectivePointSource(shape, spacing, spectrum, spectral_density, f, n, NA),
        PhaseMask(trainable(flat_phase)),
        FFLens(f, n),
    ],
    reduce_fn=lambda image: jnp.sum(image, axis=0),
)


def init_params(key, volume, z):
    params = microscope.init(key, volume, z)
    return params


@jax.jit
def compute_image(params, volume, z):
    return microscope.apply(params, volume, z)


volume = jnp.ones((128, *shape, 1))  # fill in your volume here
z = jnp.linspace(-4, 4, num=num_planes)
params = init_params(jax.random.PRNGKey(6022), volume, z)
widefield_image = compute_image(params, volume, z)
print(f"image has shape: {widefield_image.shape}")

single_gpu_times = []
for i in range(10):
    print(i)
    start = perf_counter_ns()
    _ = compute_image(params, volume, z).block_until_ready()
    end = perf_counter_ns()
    single_gpu_times.append((end - start) / 1e6)

print(f"single gpu: {np.mean(single_gpu_times)} +/- {np.std(single_gpu_times)} ms")

microscope = Microscope(
    optical_system=[
        ObjectivePointSource(shape, spacing, spectrum, spectral_density, f, n, NA),
        PhaseMask(trainable(flat_phase)),
        FFLens(f, n),
    ],
    reduce_fn=lambda image: jax.lax.psum(jnp.sum(image, axis=0), axis_name="devices"),
)


@partial(jax.pmap, axis_name="devices")
def init_params(key, volume, z):
    params = microscope.init(key, volume, z)
    return params


@partial(jax.pmap, axis_name="devices")
def compute_image(params, volume, z):
    return microscope.apply(params, volume, z)


volume = jnp.ones(
    (num_devices, num_planes_per_device, *shape, 1)
)  # fill in your volume here
z = jnp.linspace(-4, 4, num=num_planes).reshape(num_devices, num_planes_per_device)
params = init_params(jax.random.split(jax.random.PRNGKey(6022), num_devices), volume, z)
widefield_image = compute_image(params, volume, z)
print(f"image has shape: {widefield_image.shape}")
assert jnp.all(widefield_image[0] == widefield_image[1])

pmap_gpu_times = []
for i in range(10):
    print(i)
    start = perf_counter_ns()
    _ = compute_image(params, volume, z).block_until_ready()
    end = perf_counter_ns()
    pmap_gpu_times.append((end - start) / 1e6)

print(f"pmap multi gpu: {np.mean(pmap_gpu_times)} +/- {np.std(pmap_gpu_times)} ms")
