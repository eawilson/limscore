from setuptools import setup

setup(name="limscore",
    version= "0.1",
    description="Core functionallity for building a lims system.",
    url="",
    author="Ed Wilson",
    author_email="edwardadrianwilson@yahoo.co.uk",
    license="MIT",
    packages=["limscore"],
    install_requires=["sqlalchemy",
                      "alembic",
                      "flask",
                      "passlib",
                      "itsdangerous",
                      "bcrypt"],
    include_package_data=True,
    entry_points = { "console_scripts":
        ["limscore_alembic=limscore.scripts.imscore_alembic:main"] },
    zip_safe=True,
    )

