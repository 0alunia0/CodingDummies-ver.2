import matplotlib.pyplot as plt
import numpy as np

xe = np.arange(0, 18, 1)
x0 = 3  # od tego x zaczyna się wzrost (wcześniej 0)

def expo_clamped(x, r, k, x0=0):
    """
    Zwraca k * (r^(x-x0) - 1) dla x >= x0, a 0 dla x < x0.
    r > 1 -> wzrost wykładniczy, k skaluje wysokość.
    """
    y = k * (r**(x - x0) - 1)
    return np.where(x < x0, 0, y)


x = np.array([0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17])
y = np.array([0, 0, 0, 0, 6, 12, 18, 30, 48, 66, 90, 158, 192, 294, 362, 430, 464, 498])


# Scatter plot with multiple customizations
plt.plot(x, y, "g-")

x = np.array([0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17])
y = np.array([0, 0, 0, 0, 3, 6, 9, 15, 24, 33, 45, 51, 54, 133, 199, 265, 298, 331])

plt.plot(x, y, "m-")

x = np.array([0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17])
y = np.array([0, 0, 0, 0, 2.34, 4.68, 7.02, 11.7, 18.72, 25.7, 35.1, 39.7, 42.1, 49.14, 59, 125, 158, 191])

plt.plot(x, y, "r-")

y_red = expo_clamped(x, r=1.33, k=5.0, x0=x0)   # czerwona
y_mag = expo_clamped(x, r=1.42, k=6.0, x0=x0)   # fioletowa
y_grn = expo_clamped(x, r=1.55, k=6.5, x0=x0)   # zielona

plt.figure(figsize=(8,5))
plt.plot(xe, y_red, 'r', label=r'$k(r^{x-x_0}-1)$; r=1.33, k=5.0')
plt.plot(xe, y_mag, 'm', label=r'$r=1.42, k=6.0$')
plt.plot(xe, y_grn, 'g', label=r'$r=1.55, k=6.5$')


plt.xticks([0, 5,10,15,17])
plt.grid()

plt.xlabel('Lata [rok]')
plt.ylabel('Zysk pierwszego modułu [mln $]')
plt.title('Zysk jednego modułu w czasie')
plt.show()
