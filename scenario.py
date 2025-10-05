import matplotlib.pyplot as plt
import numpy as np

x = np.array([0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17])
y = np.array([0, 0, 0, 0, 6, 12, 18, 30, 48, 66, 90, 158, 192, 294, 362, 430, 464, 498])


# Scatter plot with multiple customizations
plt.plot(x, y, "g--")

x = np.array([0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17])
y = np.array([0, 0, 0, 0, 3, 6, 9, 15, 24, 33, 45, 51, 54, 133, 199, 265, 298, 331])

plt.plot(x, y, "m--")

x = np.array([0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17])
y = np.array([0, 0, 0, 0, 2.34, 4.68, 7.02, 11.7, 18.72, 25.7, 35.1, 39.7, 42.1, 49.14, 59, 125, 158, 191])

plt.plot(x, y, "r--")
plt.grid()

plt.xticks([0, 5,10,15,17])

plt.xlabel('Lata [rok]')
plt.ylabel('Zysk pierwszego modułu [mln $]')
plt.title('Zysk jednego modułu w czasie')
plt.show()
