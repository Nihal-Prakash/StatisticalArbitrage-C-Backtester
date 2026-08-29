from analyze_pair import df, symbol_a, symbol_b
import matplotlib.pyplot as plt

plt.figure(figsize=(12, 6))

plt.plot(
    df["date"],
    df["norm_a"],
    label=symbol_a
)

plt.plot(
    df["date"],
    df["norm_b"],
    label=symbol_b
)

plt.xlabel("Date")
plt.ylabel("Normalized Price")
plt.legend()

plt.tight_layout()

plt.savefig(
    "results/exploration/normalized_prices.png"
)

plt.close()

plt.figure(figsize=(12, 6))

plt.plot(
    df["date"],
    df["ret_a"],
    label=symbol_a,
    alpha=0.7
)

plt.plot(
    df["date"],
    df["ret_b"],
    label=symbol_b,
    alpha=0.7
)

plt.xlabel("Date")
plt.ylabel("Log Return")
plt.legend()

plt.tight_layout()

plt.savefig(
    "results/exploration/returns.png"
)

plt.close()
