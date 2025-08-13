To run any test files, just enter the terminal of the root directory:

./run_tests.sh                                  # run all tests
./run_tests.sh tests/alpaca_api/test_option.py  # run one file
./run_tests.sh tests/alpaca_api/test_option.py::test_parse_occ_symbol_call_put
./run_tests.sh tests/alpaca_api/test_option.py -v -k "fallback"