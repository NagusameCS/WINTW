"""Download every flag PNG from flagcdn and build the normalized array."""
from flagle.flags import download_all, build_array


def main() -> None:
    codes = download_all()
    print(f"downloaded {len(codes)} flag PNGs")
    codes, flags = build_array(codes)
    print(f"normalized array: {flags.shape}  dtype={flags.dtype}")


if __name__ == "__main__":
    main()
