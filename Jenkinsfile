def configs = [
    [
        label: 'sierra',
        pyversions: ['python3.5', 'python3.6', 'python3.7'],
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

                            # Workaround for https://github.com/pypa/pip/issues/5345
                            # See also:
                            # https://github.com/python-trio/trio/issues/508
                            # https://github.com/pypa/pip/issues/5345#issuecomment-386443351
                            export PIP_CACHE_DIR="\${PWD}/pip-cache"
                            echo PIP_CACHE_DIR=\$PIP_CACHE_DIR

                            cd trio
                            $PYVERSION -m venv .venv
                            source .venv/bin/activate

                            source ci/travis.sh
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
