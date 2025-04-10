export GATEWAY_URL=http://0.0.0.0:9100
export ASKCOS_REGISTRY=registry.gitlab.com/mlpds_mit/askcosv2/askcos2_core

docker stop deploy-app-1; docker rm deploy-app-1
docker build -f Dockerfile_app -t ${ASKCOS_REGISTRY}/app:2.0 .
docker compose -f compose.yaml up -d app
docker attach --sig-proxy=false deploy-app-1