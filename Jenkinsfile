def configs = [
    [
        label: 'sierra',
        pyversions: ['python3.5', 'python3.6'],
    ],
]


def checkout_git(label) {
    retry(3) {
        def script = ""
        if (env.BRANCH_NAME.startsWith('PR-')) {
            script = """
            git clone --depth=1 https://github.com/python-trio/trio
            cd trio
            git fetch origin +refs/pull/${env.CHANGE_ID}/merge:
            git checkout -qf FETCH_HEAD
            """
            sh """#!/bin/sh
                set -xe
                ${script}
            """
        } else {
            checkout([
                $class: 'GitSCM',
                branches: [[name: "*/${env.BRANCH_NAME}"]],
                doGenerateSubmoduleConfigurations: false,
                extensions: [[
                    $class: 'RelativeTargetDirectory',
                    relativeTargetDir: 'trio'
                ]],
                submoduleCfg: [],
                userRemoteConfigs: [[
                    'url': 'https://github.com/python-trio/trio'
                ]]
            ])
        }
    }
    sh """
        cd trio
        git rev-parse HEAD
    """
}
def build(pyversion, label) {
    try {
        timeout(time: 30, unit: 'MINUTES') {

            checkout_git(label)

            withCredentials([string(credentialsId: 'python-trio-codecov-token', variable: 'CODECOV_TOKEN')]) {
                withEnv(["LABEL=$label", "PYVERSION=$pyversion"]) {
                    ansiColor {
                        sh """#!/usr/bin/env bash
                            set -xe
                            # Jenkins logs in as a non-interactive shell, so we don't even have /usr/local/bin in PATH
                            export PATH="/usr/local/bin:\${PATH}"
                            export PATH="/Library/Frameworks/Python.framework/Versions/3.5/bin:\${PATH}"
                            export PATH="/Library/Frameworks/Python.framework/Versions/3.6/bin:\${PATH}"
                            #export PATH="/Users/jenkins/.pyenv/shims:\${PATH}"
                            cd trio
                            #virtualenv .venv -p $PYVERSION
                            $PYVERSION -m venv .venv
                            source .venv/bin/activate
                            python setup.py sdist --formats=zip
                            pip install dist/*.zip

                            pip install -Ur test-requirements.txt

                            mkdir empty
                            cd empty

                            INSTALLDIR=\$(python -c "import os, trio; print(os.path.dirname(trio.__file__))")
                            pytest -W error -ra --run-slow \${INSTALLDIR} --cov="\$INSTALLDIR" --cov-config=../.coveragerc --verbose

                            coverage combine
                            #pip install codecov && codecov
                            bash <(curl -s https://codecov.io/bash)
                        """
                    }
                }
            }
        }
    } finally {
        deleteDir()
    }

}

def builders = [:]
for (config in configs) {
    def label = config["label"]
    def pyversions = config["pyversions"]

    for (_pyversion in pyversions) {
        def pyversion = _pyversion

        def combinedName = "${label}-${pyversion}"
        builders[combinedName] = {
            node(label) {
                stage(combinedName) {
                    build(pyversion, label)
                }
            }
        }
    }
}

parallel builders
